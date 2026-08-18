"""AI 辅助生成服务测试 — 检索范围合并/暂停保留/追加覆盖落库（阶段 2）."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import assist_service

PROJECT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestTaskRegistry:
    def test_stop_without_task_returns_false(self) -> None:
        assert assist_service.stop_task(PROJECT_ID, "9") is False
        assert assist_service.is_running(PROJECT_ID, "9") is False

    def test_stop_running_task_sets_event(self) -> None:
        event = asyncio.Event()
        key = assist_service._task_key(PROJECT_ID, "8")
        assist_service._assist_tasks[key] = event
        try:
            assert assist_service.is_running(PROJECT_ID, "8")
            assert assist_service.stop_task(PROJECT_ID, "8") is True
            assert event.is_set()
        finally:
            assist_service._assist_tasks.pop(key, None)


class TestResolveAssistDocIds:
    @pytest.mark.asyncio
    async def test_no_mount_union_project_and_personal(self) -> None:
        """未配置挂载 = 项目全量 ∪ 本人个人库素材."""
        proj_doc, personal_doc = uuid.uuid4(), uuid.uuid4()
        session = AsyncMock()
        session.execute.side_effect = [
            _rows_result([(proj_doc,)]),  # 项目全量文档
            _rows_result([(uuid.uuid4(),)]),  # 本人个人库 id
            _rows_result([(personal_doc,)]),  # 个人库内素材
        ]
        result = await assist_service.resolve_assist_doc_ids(
            session, PROJECT_ID, USER_ID, None, None
        )
        assert result == sorted([proj_doc, personal_doc], key=str)

    @pytest.mark.asyncio
    async def test_mounted_union_personal(self) -> None:
        """显式挂载文档 ∪ 个人库素材（去重）."""
        mounted_doc, personal_doc = uuid.uuid4(), uuid.uuid4()
        session = AsyncMock()
        session.execute.side_effect = [
            _rows_result([(uuid.uuid4(),)]),  # 本人个人库 id（mounted_doc_ids 直接解析不查库）
            _rows_result([(personal_doc,)]),  # 个人库内素材
        ]
        result = await assist_service.resolve_assist_doc_ids(
            session, PROJECT_ID, USER_ID, None, [str(mounted_doc)]
        )
        assert result == sorted([mounted_doc, personal_doc], key=str)


class TestAssistGenerate:
    def _patch_runtime(self, monkeypatch, chapters: dict) -> dict:
        captured: dict = {"updates": [], "sections": [], "events": []}

        snapshot = MagicMock()
        snapshot.values = {
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": chapters,
            "chapter_summaries": {},
            "score_points": [],
            "tech_requirements": [],
        }

        async def fake_get_state(pid):
            return snapshot

        async def fake_update_state(pid, updates):
            captured["updates"].append(updates)

        async def fake_generate(**kwargs):
            captured["generate_kwargs"] = kwargs
            event = kwargs.get("stop_event")
            if captured.get("simulate_stop") and event is not None:
                event.set()
                return "已生成的部分"
            return "新生成的正文内容"

        async def fake_upsert(db, pid, chapter_no, title, content, status=None):
            captured["sections"].append((chapter_no, content, status))

        async def fake_publish(pid, event):
            captured["events"].append(event)

        session = AsyncMock()
        session.execute.return_value = _rows_result([])

        def fake_session_factory():
            return _FakeSession(session)

        monkeypatch.setattr("app.services.workflow_runtime.get_state", fake_get_state)
        monkeypatch.setattr("app.services.workflow_runtime.update_state", fake_update_state)
        monkeypatch.setattr("app.services.chapter_service.generate_chapter", fake_generate)
        monkeypatch.setattr("app.agents.nodes._upsert_section", fake_upsert)
        monkeypatch.setattr("app.services.assist_service.publish_event", fake_publish)
        monkeypatch.setattr("app.core.database.async_session_factory", fake_session_factory)
        return captured

    @pytest.mark.asyncio
    async def test_append_mode_persists_merged_content(self, monkeypatch) -> None:
        """append：现有正文 + 新部分合并双写（state + proposal_sections draft）."""
        captured = self._patch_runtime(monkeypatch, {"1": "原有正文"})
        result = await assist_service.assist_generate(PROJECT_ID, "1", USER_ID, mode="append")
        assert result["stopped"] is False
        assert result["content"] == "原有正文\n\n新生成的正文内容"
        assert captured["sections"] == [("1", "原有正文\n\n新生成的正文内容", "draft")]
        assert captured["updates"][0]["chapters"]["1"] == result["content"]
        done_events = [e for e in captured["events"] if e["type"] == "section_done"]
        assert done_events and done_events[0]["source"] == "assist"

    @pytest.mark.asyncio
    async def test_overwrite_mode_replaces_content(self, monkeypatch) -> None:
        """overwrite：整章覆盖（不保留原正文）."""
        captured = self._patch_runtime(monkeypatch, {"1": "原有正文"})
        result = await assist_service.assist_generate(PROJECT_ID, "1", USER_ID, mode="overwrite")
        assert result["content"] == "新生成的正文内容"
        assert captured["sections"] == [("1", "新生成的正文内容", "draft")]

    @pytest.mark.asyncio
    async def test_stop_keeps_partial_and_marks_stopped(self, monkeypatch) -> None:
        """暂停：已生成部分仍按 mode 落库，返回 stopped=True."""
        captured = self._patch_runtime(monkeypatch, {})
        captured["simulate_stop"] = True
        result = await assist_service.assist_generate(PROJECT_ID, "1", USER_ID, mode="append")
        assert result["stopped"] is True
        assert result["content"] == "已生成的部分"
        assert captured["sections"] == [("1", "已生成的部分", "draft")]
        # 任务注册表清理
        assert not assist_service.is_running(PROJECT_ID, "1")

    @pytest.mark.asyncio
    async def test_concurrent_task_rejected(self, monkeypatch) -> None:
        """同章节已有辅助生成任务 → BizError（防并发重复生成）."""
        self._patch_runtime(monkeypatch, {})
        assist_service._assist_tasks[assist_service._task_key(PROJECT_ID, "1")] = asyncio.Event()
        try:
            with pytest.raises(Exception) as exc_info:
                await assist_service.assist_generate(PROJECT_ID, "1", USER_ID)
            assert getattr(exc_info.value, "code", None) == 4000
        finally:
            assist_service._assist_tasks.pop(assist_service._task_key(PROJECT_ID, "1"), None)


class _FakeSession:
    """async_session_factory 桩：上下文管理器包装 AsyncMock session."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return None
