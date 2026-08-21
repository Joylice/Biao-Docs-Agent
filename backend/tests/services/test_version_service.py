"""版本库服务测试 — Markdown 源拼装 / 快照续号 / 自动触发条件（阶段 6）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project
from app.models.proposal import ProposalSection, ProposalVersion
from app.services import version_service


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_build_markdown_source_structure() -> None:
    """Markdown 源含项目标题/章标题/子节/正文."""
    text = version_service.build_markdown_source(
        "智慧城市项目",
        [{"chapter_no": "1", "title": "概述", "sections": ["背景", "目标"]}],
        {"1": "正文内容"},
    )
    assert "# 智慧城市项目" in text
    assert "## 1 概述" in text
    assert "### 背景" in text
    assert "正文内容" in text


def test_build_markdown_source_without_outline() -> None:
    """outline 缺失时按 chapters 兜底输出."""
    text = version_service.build_markdown_source("项目", [], {"2": "兜底内容"})
    assert "## 2" in text
    assert "兜底内容" in text


@pytest.mark.asyncio
async def test_create_snapshot_version_increment(monkeypatch) -> None:
    """version 续号：max=2 → 新版本 3；Word/Markdown 源 storage_key 落库."""
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result(2))

    snapshot = MagicMock()
    snapshot.values = {
        "chapters": {"1": "内容"},
        "outline": [{"chapter_no": "1", "title": "概述"}],
        "project_name": "测试项目",
    }
    monkeypatch.setattr(
        version_service.workflow_runtime, "get_state", AsyncMock(return_value=snapshot)
    )
    export_mock = AsyncMock(return_value="versions/pid/x.docx")
    monkeypatch.setattr(version_service, "export_to_word", export_mock)
    monkeypatch.setattr(version_service, "upload_file", MagicMock(return_value="versions/pid/p.md"))
    monkeypatch.setattr(
        version_service, "_latest_format_requirements", AsyncMock(return_value=None)
    )

    pid = uuid.uuid4()
    record = await version_service.create_snapshot(
        session, pid, "回退名", user_id=uuid.uuid4(), snapshot_note="手动快照"
    )
    assert record.version == 3
    assert record.project_id == pid
    assert record.storage_key_docx == "versions/pid/x.docx"
    assert record.storage_key_source == "versions/pid/p.md"
    assert record.snapshot_note == "手动快照"
    assert record.created_by is not None
    # 阶段 E5：结构化快照落库（回滚数据源）
    assert record.snapshot_json == {
        "outline": [{"chapter_no": "1", "title": "概述"}],
        "chapters": {"1": "内容"},
    }
    export_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_snapshot_requires_chapters(monkeypatch) -> None:
    """无章节内容时拒绝快照."""
    session = AsyncMock()
    snapshot = MagicMock()
    snapshot.values = {"chapters": {}, "outline": []}
    monkeypatch.setattr(
        version_service.workflow_runtime, "get_state", AsyncMock(return_value=snapshot)
    )
    with pytest.raises(ValidationError):
        await version_service.create_snapshot(session, uuid.uuid4(), "项目")


@pytest.mark.asyncio
async def test_maybe_auto_snapshot_blocked_by_in_progress(monkeypatch) -> None:
    """存在 pending/in_progress/submitted → 不触发."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_rows_result([("approved",), ("submitted",)]))
    create = AsyncMock()
    monkeypatch.setattr(version_service, "create_snapshot", create)
    assert await version_service.maybe_auto_snapshot(session, uuid.uuid4(), "项目") is None
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_auto_snapshot_requires_approved(monkeypatch) -> None:
    """全部定稿但无 approved（如仅 rejected）→ 不触发."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_rows_result([("rejected",)]))
    create = AsyncMock()
    monkeypatch.setattr(version_service, "create_snapshot", create)
    assert await version_service.maybe_auto_snapshot(session, uuid.uuid4(), "项目") is None
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_auto_snapshot_triggers(monkeypatch) -> None:
    """满足条件 → 自动快照（created_by NULL）并 commit."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_rows_result([("approved",), ("approved",)]))
    record = MagicMock()
    create = AsyncMock(return_value=record)
    monkeypatch.setattr(version_service, "create_snapshot", create)
    pid = uuid.uuid4()
    result = await version_service.maybe_auto_snapshot(session, pid, "项目")
    assert result is record
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["user_id"] is None
    assert kwargs["snapshot_note"] == "自动快照：全部章节审核通过"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_maybe_auto_snapshot_failure_not_blocking(monkeypatch) -> None:
    """快照失败回滚并返回 None，不阻塞审核主流程."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_rows_result([("approved",)]))
    monkeypatch.setattr(
        version_service, "create_snapshot", AsyncMock(side_effect=RuntimeError("boom"))
    )
    assert await version_service.maybe_auto_snapshot(session, uuid.uuid4(), "项目") is None
    session.rollback.assert_awaited()


# ── 阶段 E5：版本回滚 ──


def _version_record(pid: uuid.UUID, snapshot_json: dict | None) -> ProposalVersion:
    return ProposalVersion(
        id=uuid.uuid4(),
        project_id=pid,
        version=1,
        snapshot_note=None,
        storage_key_docx="versions/x/a.docx",
        storage_key_source="versions/x/a.md",
        created_by=None,
        snapshot_json=snapshot_json,
    )


@pytest.mark.asyncio
async def test_rollback_version_writes_back_sections(monkeypatch) -> None:
    """回滚：章级行内容回写 + 状态置 draft + 图状态同步."""
    pid = uuid.uuid4()
    section = ProposalSection(
        project_id=pid,
        section_id="1",
        title="概述",
        content_md="旧内容",
        status="approved",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = section
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=result)
    update_state = AsyncMock()
    monkeypatch.setattr(version_service.workflow_runtime, "update_state", update_state)

    record = _version_record(
        pid,
        {
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {"1": "恢复的正文"},
        },
    )
    count = await version_service.rollback_version(session, pid, record)
    assert count == 1
    assert section.content_md == "恢复的正文"
    assert section.status == "draft"
    update_state.assert_awaited_once()
    values = update_state.await_args.args[1]
    assert values["chapters"] == {"1": "恢复的正文"}


@pytest.mark.asyncio
async def test_rollback_version_creates_missing_section(monkeypatch) -> None:
    """章节行不存在时新建（标题取自大纲）."""
    pid = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(version_service.workflow_runtime, "update_state", AsyncMock())
    record = _version_record(
        pid,
        {
            "outline": [{"chapter_no": "2", "title": "架构", "sections": []}],
            "chapters": {"2": "正文"},
        },
    )
    count = await version_service.rollback_version(session, pid, record)
    assert count == 1
    added = session.add.call_args.args[0]
    assert isinstance(added, ProposalSection)
    assert added.title == "架构"
    assert added.content_md == "正文"


@pytest.mark.asyncio
async def test_rollback_version_requires_snapshot_json() -> None:
    """旧版本无结构化快照 → 拒绝回滚."""
    pid = uuid.uuid4()
    with pytest.raises(ValidationError):
        await version_service.rollback_version(AsyncMock(), pid, _version_record(pid, None))


# ── 批次 1a：api 层查询/归档 DB 操作下沉 ──


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project(pid: uuid.UUID, owner_id: uuid.UUID) -> Project:
    return Project(id=pid, name="测试项目", owner_id=owner_id, status="active")


class TestGetProjectAndVersion:
    @pytest.mark.asyncio
    async def test_get_project_not_found(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(NotFoundError):
            await version_service.get_project(session, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_version_not_found_or_mismatch(self) -> None:
        """版本不存在或 project 不匹配 → NotFoundError."""
        pid = uuid.uuid4()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(NotFoundError):
            await version_service.get_version(session, pid, uuid.uuid4())

        other = _version_record(uuid.uuid4(), None)
        session.execute = AsyncMock(return_value=_result(other))
        with pytest.raises(NotFoundError):
            await version_service.get_version(session, pid, other.id)

    @pytest.mark.asyncio
    async def test_get_version_ok(self) -> None:
        pid = uuid.uuid4()
        record = _version_record(pid, None)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(record))
        assert await version_service.get_version(session, pid, record.id) is record


class TestListVersions:
    @pytest.mark.asyncio
    async def test_serialization_desc_and_auto_flag(self) -> None:
        """version 倒序；created_by NULL 标记 auto，created_by_name 随之为 None."""
        pid = uuid.uuid4()
        owner = uuid.uuid4()
        v2 = _version_record(pid, None)
        v2.version = 2
        v2.created_by = owner
        v1 = _version_record(pid, None)
        v1.version = 1
        v1.created_by = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_rows_result([(v2, "张三"), (v1, None)]))
        items = await version_service.list_versions(session, pid)
        assert [i["version"] for i in items] == [2, 1]
        assert items[0]["created_by_name"] == "张三"
        assert items[0]["auto"] is False
        assert items[1]["auto"] is True
        assert items[1]["created_by_name"] is None
        assert "DESC" in str(session.execute.await_args.args[0])


class TestArchiveVersion:
    def _base(self, scope: str = "company") -> KnowledgeBase:
        return KnowledgeBase(
            id=uuid.uuid4(), name="公司公共库", scope=scope, owner_id=None, project_id=None
        )

    @pytest.mark.asyncio
    async def test_rejects_non_company_base(self) -> None:
        """非公司级知识库 → ValidationError（400）."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(self._base("personal")))
        with pytest.raises(ValidationError):
            await version_service.archive_version(
                session, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_unknown_base_404(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(NotFoundError):
            await version_service.archive_version(
                session, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_registers_global_material(self) -> None:
        """归档：登记全局素材（project_id NULL + kb_id）+ flush/refresh；入队由 api 层执行."""
        pid = uuid.uuid4()
        owner = uuid.uuid4()
        base = self._base("company")
        version = _version_record(pid, None)
        version.version = 2
        project = _project(pid, owner)
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(side_effect=[_result(base), _result(version), _result(project)])
        data = await version_service.archive_version(session, pid, version.id, base.id, owner)
        doc = session.add.call_args.args[0]
        assert isinstance(doc, Document)
        assert doc.project_id is None
        assert doc.kb_id == base.id
        assert doc.doc_type == "kb_material"
        assert doc.storage_key == version.storage_key_docx
        session.flush.assert_awaited()
        session.refresh.assert_awaited()
        assert data["version"] == 2
        assert data["document_id"] == doc.id
        assert data["kb_id"] == str(base.id)
        assert data["title"] == "归档-测试项目-v2"
        session.commit.assert_not_awaited()  # commit 位置保留在 api 层（BUG-1 约定）
