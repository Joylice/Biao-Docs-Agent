"""版本库 API 测试 — GET/POST versions、download、archive（阶段 6）."""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

import app.api.versions as versions_api
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.core.security import create_access_token
from app.main import app
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project
from app.models.proposal import ProposalVersion

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _join_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


def _version(version: int = 1, created_by: uuid.UUID | None = None) -> ProposalVersion:
    return ProposalVersion(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        version=version,
        snapshot_note=None,
        storage_key_docx="versions/x/a.docx",
        storage_key_source="versions/x/a.md",
        created_by=created_by,
    )


def _base(scope: str = "company") -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(), name="公司公共库", scope=scope, owner_id=None, project_id=None
    )


@pytest.fixture
def override_db() -> Generator:
    def _override(results: list) -> AsyncMock:
        session = AsyncMock()
        session.add = MagicMock()
        session.execute.side_effect = results
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/versions"


@pytest.mark.asyncio
async def test_list_versions_no_auth(client: AsyncClient) -> None:
    """未认证读取版本列表返回 401."""
    resp = await client.get(_url())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_versions_member(
    client: AsyncClient, override_db, monkeypatch
) -> None:
    """成员读取：version 倒序，created_by NULL 标记 auto."""
    session = override_db(
        [
            _result(_project()),  # _check_project_member（owner 直通）
            _join_result([(_version(2, OWNER_ID), "张三"), (_version(1, None), None)]),
        ]
    )
    resp = await client.get(_url(), headers=_headers(OWNER_ID))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert [i["version"] for i in items] == [2, 1]
    assert items[0]["created_by_name"] == "张三"
    assert items[0]["auto"] is False
    assert items[1]["auto"] is True
    assert session is not None


@pytest.mark.asyncio
async def test_list_versions_non_member_403(client: AsyncClient, override_db) -> None:
    """非成员读取 403."""
    override_db([_result(_project()), _result(None)])
    resp = await client.get(_url(), headers=_headers(uuid.uuid4()))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_version_owner(client: AsyncClient, override_db, monkeypatch) -> None:
    """owner 手动快照：调 create_snapshot + 审计 + commit."""
    session = override_db([_result(_project()), _result(_project())])
    record = _version(3, OWNER_ID)
    create = AsyncMock(return_value=record)
    monkeypatch.setattr(versions_api.version_service, "create_snapshot", create)
    resp = await client.post(
        _url(), headers=_headers(OWNER_ID), json={"snapshot_note": "评审定稿"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 3
    create.assert_awaited_once()
    assert create.await_args.kwargs["snapshot_note"] == "评审定稿"
    assert create.await_args.kwargs["user_id"] == OWNER_ID
    actions = [c.args[0].action for c in session.add.call_args_list]
    assert "version.snapshot" in actions
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_version_non_owner_403(client: AsyncClient, override_db) -> None:
    """非 owner 手动快照 403."""
    override_db([_result(_project())])
    resp = await client.post(_url(), headers=_headers(MEMBER_ID))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_download_version_docx(
    client: AsyncClient, override_db, monkeypatch
) -> None:
    """成员下载 docx：返回签名 URL."""
    override_db(
        [
            _result(_project()),  # 成员校验（owner 直通）
            _result(_version(1)),
        ]
    )
    monkeypatch.setattr(
        versions_api, "presigned_url", MagicMock(return_value="http://minio/a.docx?sig=x")
    )
    resp = await client.get(f"{_url()}/{_version(1).id}/download", headers=_headers(OWNER_ID))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["url"] == "http://minio/a.docx?sig=x"
    assert data["storage_key"] == "versions/x/a.docx"


@pytest.mark.asyncio
async def test_download_version_source_key(
    client: AsyncClient, override_db, monkeypatch
) -> None:
    """type=source 下载 Markdown 源的 storage_key."""
    override_db([_result(_project()), _result(_version(1))])
    captured: list = []
    monkeypatch.setattr(
        versions_api,
        "presigned_url",
        MagicMock(side_effect=lambda key: captured.append(key) or "http://minio/u"),
    )
    resp = await client.get(
        f"{_url()}/{_version(1).id}/download?type=source", headers=_headers(OWNER_ID)
    )
    assert resp.status_code == 200
    assert captured == ["versions/x/a.md"]


@pytest.mark.asyncio
async def test_archive_to_company_base(
    client: AsyncClient, override_db, monkeypatch
) -> None:
    """归档公司库：登记全局素材（project_id NULL + kb_id）+ 入队向量化 + 审计."""
    base = _base("company")
    version = _version(2)
    session = override_db(
        [
            _result(_project()),  # get_current_owner_id
            _result(base),
            _result(version),
            _result(_project()),
        ]
    )
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(versions_api.task_service, "enqueue_index_document", enqueue)
    resp = await client.post(
        f"{_url()}/{version.id}/archive",
        headers=_headers(OWNER_ID),
        json={"kb_id": str(base.id)},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["version"] == 2
    assert data["title"] == "归档-测试项目-v2"
    doc = session.add.call_args_list[0].args[0]
    assert isinstance(doc, Document)
    assert doc.project_id is None
    assert doc.kb_id == base.id
    assert doc.doc_type == "kb_material"
    assert doc.storage_key == version.storage_key_docx
    actions = [
        c.args[0].action for c in session.add.call_args_list if hasattr(c.args[0], "action")
    ]
    assert "proposal.archive" in actions
    session.commit.assert_awaited()
    enqueue.assert_awaited_once_with(None, doc.id)


@pytest.mark.asyncio
async def test_archive_personal_base_rejected(
    client: AsyncClient, override_db
) -> None:
    """归档目标非公司级库 → 400."""
    override_db([_result(_project()), _result(_base("personal"))])
    resp = await client.post(
        f"{_url()}/{_version(1).id}/archive",
        headers=_headers(OWNER_ID),
        json={"kb_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_archive_non_owner_403(client: AsyncClient, override_db) -> None:
    """非 owner 归档 403."""
    override_db([_result(_project())])
    resp = await client.post(
        f"{_url()}/{_version(1).id}/archive",
        headers=_headers(MEMBER_ID),
        json={"kb_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


class TestRollbackVersion:
    """阶段 E5：版本回滚（回写 proposal_sections + 审计 version.rollback）."""

    @pytest.mark.asyncio
    async def test_owner_rollback_with_audit(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """owner 回滚：调 rollback_version + 审计 + commit."""
        version = _version(2)
        session = override_db([_result(_project()), _result(version)])
        rollback = AsyncMock(return_value=3)
        monkeypatch.setattr(versions_api.version_service, "rollback_version", rollback)
        resp = await client.post(
            f"{_url()}/{version.id}/rollback", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["version"] == 2
        assert data["chapters_restored"] == 3
        rollback.assert_awaited_once()
        actions = [
            c.args[0].action
            for c in session.add.call_args_list
            if hasattr(c.args[0], "action")
        ]
        assert "version.rollback" in actions
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_rollback_without_snapshot_400(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """无结构化快照的旧版本回滚 → 400."""
        version = _version(1)
        override_db([_result(_project()), _result(version)])
        monkeypatch.setattr(
            versions_api.version_service,
            "rollback_version",
            AsyncMock(side_effect=ValidationError("该版本无结构化快照")),
        )
        resp = await client.post(
            f"{_url()}/{version.id}/rollback", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rollback_non_owner_403(
        self, client: AsyncClient, override_db
    ) -> None:
        """非 owner 回滚 403."""
        override_db([_result(_project())])
        resp = await client.post(
            f"{_url()}/{_version(1).id}/rollback", headers=_headers(MEMBER_ID)
        )
        assert resp.status_code == 403
