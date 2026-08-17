"""文档 API 测试."""

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import ScorePoint
from app.models.project import Project


@pytest.mark.asyncio
async def test_upload_document_no_auth(client: AsyncClient) -> None:
    """未认证上传文档返回 401."""
    import io

    files = {"file": ("test.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/documents",
        files=files,
        params={"doc_type": "tender_file"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_documents_no_auth(client: AsyncClient) -> None:
    """未认证列出文档返回 401."""
    response = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000001/documents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_score_points_no_auth(client: AsyncClient) -> None:
    """未认证列出评分点返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/score-points"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tech_requirements_no_auth(client: AsyncClient) -> None:
    """未认证列出技术需求返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/tech-requirements"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_score_point_no_auth(client: AsyncClient) -> None:
    """未认证更新评分点返回 401."""
    response = await client.put(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/score-points/00000000-0000-0000-0000-000000000001",
        json={"strategy": "test"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalid_file_type(client: AsyncClient) -> None:
    """上传不支持的文件类型 — 需要认证所以先返回 401."""
    import io

    files = {"file": ("test.exe", io.BytesIO(b"fake"), "application/x-msdownload")}
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/documents",
        files=files,
        params={"doc_type": "tender_file"},
    )
    # 没有 token 所以先返回 401
    assert response.status_code == 401


# ── 上传成功后异步入队（task_service）──


class _FakeUploadSession:
    """mock 会话：成员校验返回 owner；flush 时补齐主键、refresh 时补齐 created_at.

    BUG-1 适配：记录 commit 调用（写路径显式提交，get_db 不再兜底 commit）。
    """

    def __init__(self, project) -> None:
        self._project = project
        self.added: list = []
        self.committed = False

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._project
        return result

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, obj) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def upload_env(monkeypatch):
    """上传端点环境：mock 会话/对象存储/任务入队，真实 JWT 鉴权."""
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models.project import Project

    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=user_id)
    session = _FakeUploadSession(project)
    app.dependency_overrides[get_db] = lambda: session

    monkeypatch.setattr("app.api.documents.upload_file", lambda *a, **k: "mock/storage/key")

    calls: dict[str, list] = {"parse": [], "index": []}

    async def fake_enqueue_parse(pid, did):
        calls["parse"].append((pid, did))
        return True

    async def fake_enqueue_index(pid, did):
        calls["index"].append((pid, did))
        return True

    monkeypatch.setattr("app.services.task_service.enqueue_parse_tender", fake_enqueue_parse)
    monkeypatch.setattr("app.services.task_service.enqueue_index_document", fake_enqueue_index)

    yield {
        "user_id": user_id,
        "project_id": project_id,
        "session": session,
        "calls": calls,
        "headers": {"Authorization": f"Bearer {create_access_token(str(user_id))}"},
    }
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_tender_file_enqueues_parse(client: AsyncClient, upload_env) -> None:
    """招标文件上传成功 → 入队 task_parse_tender（不入队向量化）."""
    files = {"file": ("tender.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        f"/api/v1/projects/{upload_env['project_id']}/documents",
        files=files,
        params={"doc_type": "tender_file"},
        headers=upload_env["headers"],
    )
    assert response.status_code == 200
    doc_id = uuid.UUID(response.json()["data"]["id"])
    assert upload_env["calls"]["parse"] == [(upload_env["project_id"], doc_id)]
    assert upload_env["calls"]["index"] == []
    # 上传端点只入队，状态推进由 worker 负责，仍为 uploaded
    assert response.json()["data"]["status"] == "uploaded"


@pytest.mark.asyncio
async def test_upload_kb_material_enqueues_index(client: AsyncClient, upload_env) -> None:
    """资料库文档上传成功 → 入队 task_index_document（不入队解析）."""
    files = {"file": ("kb.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        f"/api/v1/projects/{upload_env['project_id']}/documents",
        files=files,
        params={"doc_type": "kb_material"},
        headers=upload_env["headers"],
    )
    assert response.status_code == 200
    doc_id = uuid.UUID(response.json()["data"]["id"])
    assert upload_env["calls"]["index"] == [(upload_env["project_id"], doc_id)]
    assert upload_env["calls"]["parse"] == []


# ── BUG-1：写路径在响应返回前显式 commit ──


@pytest.mark.asyncio
async def test_upload_commits_before_enqueue(client: AsyncClient, upload_env) -> None:
    """上传登记 + 审计显式提交（worker 领取任务时文档行必须已可见）."""
    files = {"file": ("kb.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        f"/api/v1/projects/{upload_env['project_id']}/documents",
        files=files,
        params={"doc_type": "kb_material"},
        headers=upload_env["headers"],
    )
    assert response.status_code == 200
    assert upload_env["session"].committed is True


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.mark.asyncio
async def test_update_score_point_commits_before_response(client: AsyncClient) -> None:
    """BUG-1：评分点更新显式提交（确认状态对后续工作流立即可见）."""
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    sp_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    sp = ScorePoint(
        id=sp_id,
        project_id=project_id,
        doc_id=uuid.uuid4(),
        clause_no="1",
        item="技术方案完整性",
        is_star=False,
    )

    session = AsyncMock()
    session.execute.side_effect = [_result(project), _result(sp)]
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.put(
            f"/api/v1/projects/{project_id}/score-points/{sp_id}",
            json={"confirmed": True},
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        session.commit.assert_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 重新解析（reparse）──


def _make_tender_doc(project_id: uuid.UUID, status: str = "parsed", doc_type: str = "tender_file"):
    from app.models.document import Document

    return Document(
        id=uuid.uuid4(),
        project_id=project_id,
        doc_type=doc_type,
        title="招标文件.docx",
        storage_key=f"{project_id}/tender.docx",
        status=status,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def reparse_env(monkeypatch):
    """reparse 端点环境：mock 会话/审计/入队，真实 JWT 鉴权."""
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    doc = _make_tender_doc(project_id, status="parsed")

    session = AsyncMock()
    # execute 序列：成员校验 → 文档查询 → 删评分点 → 删衍生需求
    # （招标原文技术需求保留：重新解析只负责评分点提取）
    session.execute.side_effect = [
        _result(project),
        _result(doc),
        _result(None),
        _result(None),
    ]
    app.dependency_overrides[get_db] = lambda: session

    enqueue_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.task_service.enqueue_parse_tender", enqueue_mock)
    monkeypatch.setattr("app.core.audit.record", AsyncMock())

    yield {
        "owner_id": owner_id,
        "project_id": project_id,
        "doc": doc,
        "session": session,
        "enqueue": enqueue_mock,
        "headers": {"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
    }
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_reparse_no_auth(client: AsyncClient) -> None:
    """未认证重新解析返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/"
        "documents/00000000-0000-0000-0000-000000000002/reparse"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reparse_clears_old_results_and_reenqueues(client: AsyncClient, reparse_env) -> None:
    """重新解析：清除旧评分点/衍生需求 → 状态重置 → 仅评分点模式入队 → 显式提交."""
    doc = reparse_env["doc"]
    response = await client.post(
        f"/api/v1/projects/{reparse_env['project_id']}/documents/{doc.id}/reparse",
        headers=reparse_env["headers"],
    )
    assert response.status_code == 200, response.text
    assert doc.status == "uploaded", "文档状态应重置为 uploaded 等待 worker 重新推进"
    assert response.json()["data"]["status"] == "uploaded"
    # 重新解析只负责评分点提取：入队带 score_points_only=True（跳过技术需求提取）
    reparse_env["enqueue"].assert_awaited_once_with(
        reparse_env["project_id"], doc.id, score_points_only=True
    )
    reparse_env["session"].commit.assert_awaited()
    # 旧解析结果删除：两条 DELETE（score_points 按 doc_id + 项目级 sp_derived 衍生需求）；
    # 招标原文技术需求（source=NULL/tender）不被清除
    deletes = [
        c
        for c in reparse_env["session"].execute.call_args_list
        if str(c.args[0]).lstrip().upper().startswith("DELETE")
    ]
    assert len(deletes) == 2, "应删除旧评分点与基于旧评分点的衍生需求，保留招标原文技术需求"
    delete_params = [str(c.args[0].compile().params) for c in deletes]
    assert any("sp_derived" in p for p in delete_params), "应清除项目级 sp_derived 衍生需求"
    assert all(
        "score_points" in str(c.args[0]) or "sp_derived" in str(c.args[0].compile().params)
        for c in deletes
    ), "不得出现按 doc_id 删除招标原文技术需求的语句"


@pytest.mark.asyncio
async def test_reparse_rejects_parsing_doc(client: AsyncClient, reparse_env) -> None:
    """解析中的文档不允许重复提交重新解析."""
    reparse_env["doc"].status = "parsing"
    response = await client.post(
        f"/api/v1/projects/{reparse_env['project_id']}/documents/{reparse_env['doc'].id}/reparse",
        headers=reparse_env["headers"],
    )
    assert response.status_code == 400
    assert response.json()["code"] == 4010
    reparse_env["enqueue"].assert_not_awaited()


@pytest.mark.asyncio
async def test_reparse_rejects_kb_material(client: AsyncClient, reparse_env) -> None:
    """资料库文档不支持重新解析（仅招标文件）."""
    reparse_env["doc"].doc_type = "kb_material"
    response = await client.post(
        f"/api/v1/projects/{reparse_env['project_id']}/documents/{reparse_env['doc'].id}/reparse",
        headers=reparse_env["headers"],
    )
    assert response.status_code == 400
    assert response.json()["code"] == 4010
    reparse_env["enqueue"].assert_not_awaited()


@pytest.mark.asyncio
async def test_reparse_missing_doc(client: AsyncClient, reparse_env) -> None:
    """文档不存在返回 4004."""
    project = Project(
        id=reparse_env["project_id"], name="测试项目", owner_id=reparse_env["owner_id"]
    )
    missing_session = AsyncMock()
    missing_session.execute.side_effect = [_result(project), _result(None)]
    app.dependency_overrides[get_db] = lambda: missing_session
    response = await client.post(
        f"/api/v1/projects/{reparse_env['project_id']}/documents/{uuid.uuid4()}/reparse",
        headers=reparse_env["headers"],
    )
    assert response.status_code == 404
    assert response.json()["code"] == 4004
