"""版本库服务测试 — Markdown 源拼装 / 快照续号 / 自动触发条件（阶段 6）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ValidationError
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
    monkeypatch.setattr(
        version_service, "upload_file", MagicMock(return_value="versions/pid/p.md")
    )
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
    session.execute = AsyncMock(
        return_value=_rows_result([("approved",), ("submitted",)])
    )
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
    session.execute = AsyncMock(
        return_value=_rows_result([("approved",), ("approved",)])
    )
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
