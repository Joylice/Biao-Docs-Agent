"""workflow_runtime 服务测试 — InMemorySaver 驱动真实图执行（LLM mock 模式）."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import nodes
from app.core.config import settings
from app.core.exceptions import BizError
from app.services import workflow_runtime
from tests.agents.test_graph import make_fake_db

PROJECT_ID = uuid.uuid4()
FAKE_EXPORT_KEY = f"{PROJECT_ID}/export/runtime-test.docx"


@pytest.fixture
def memory_runtime(monkeypatch):
    """注入 InMemorySaver 作为 checkpointer，用例结束清理."""
    workflow_runtime.set_saver(InMemorySaver())
    yield
    workflow_runtime.set_saver(None)


@pytest.fixture
def mock_node_deps(monkeypatch):
    """mock 节点外部依赖（DB/事件/导出），LLM 走 mock 模式."""

    async def fake_publish_event(_project_id: str, _event: dict) -> None:
        pass

    def fake_session_factory():
        return make_fake_db()

    async def fake_export_to_word(**kwargs) -> str:
        return FAKE_EXPORT_KEY

    async def fake_get_embedding(_text: str):
        return []

    async def fake_retrieve_similar(**kwargs):
        return []

    async def fake_call_llm_with_schema(**kwargs) -> dict:
        return {
            "chapters": [
                {"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]},
                {"chapter_no": "2", "title": "技术方案", "sections": ["架构", "实现"]},
            ]
        }

    monkeypatch.setattr(settings, "llm_mock", True)
    monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
    monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", fake_call_llm_with_schema)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.export_service.export_to_word", fake_export_to_word)


class TestRunAndResume:
    """run/resume 驱动真实图，HITL interrupt 逐段推进."""

    @pytest.mark.asyncio
    async def test_run_stops_at_score_points_interrupt(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """首次 run 停在评分点 interrupt，score_points 来自 DB 非硬编码空值."""
        result = await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        assert result["__interrupt__"][0].value["type"] == "confirm_score_points"

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        values = snapshot.values
        assert values["score_points"], "parse 节点应从 DB 读出评分点"
        assert values["score_points"][0]["item"] == "技术方案完整性"
        assert values["current_phase"] == "confirm"

    @pytest.mark.asyncio
    async def test_resume_advances_through_hitl_nodes(self, memory_runtime, mock_node_deps) -> None:
        """confirm → outline interrupt → review interrupt → approved 完成."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())

        # 确认评分点 → 停在大纲 interrupt
        result = await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        assert result["__interrupt__"][0].value["type"] == "confirm_outline"

        # 确认大纲 → 章节生成 → 停在审阅 interrupt
        result = await workflow_runtime.resume_workflow(PROJECT_ID, True)
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert set(result["chapters"].keys()) == {"1", "2"}

        # 审阅通过 → 导出完成
        result = await workflow_runtime.resume_workflow(PROJECT_ID, {"action": "approved"})
        assert result["export_status"] == "done"
        assert result["current_phase"] == "done"

    @pytest.mark.asyncio
    async def test_get_status_reports_phase_and_progress(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """get_status_dict 的 phase/progress/interrupt 随执行变化."""
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["phase"] == "init"
        assert status["progress"] == 0.0
        assert status["interrupt"] is None

        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["phase"] == "confirm"
        assert status["progress"] == pytest.approx(0.15)
        assert status["interrupt"]["type"] == "confirm_score_points"
        assert status["score_points"]

        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["interrupt"]["type"] == "confirm_outline"
        assert status["outline"], "mock LLM 应产出大纲"


class TestRewriteAndExport:
    """章节重写与导出的状态回写."""

    async def _advance_to_review(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(PROJECT_ID, True)

    @pytest.mark.asyncio
    async def test_rewrite_chapter_merges_into_state(self, memory_runtime, mock_node_deps) -> None:
        """重写结果经 checkpointer 回写 chapters."""
        await self._advance_to_review()
        new_content = await workflow_runtime.rewrite_chapter(PROJECT_ID, "1", "补充项目范围")
        assert new_content

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        chapters = snapshot.values["chapters"]
        assert chapters["1"] == new_content
        assert "2" in chapters, "其余章节不受影响"

    @pytest.mark.asyncio
    async def test_rewrite_missing_chapter_raises(self, memory_runtime, mock_node_deps) -> None:
        await self._advance_to_review()
        with pytest.raises(BizError):
            await workflow_runtime.rewrite_chapter(PROJECT_ID, "99", "意见")

    @pytest.mark.asyncio
    async def test_export_workflow_reuses_export_node(self, memory_runtime, mock_node_deps) -> None:
        """导出复用图内 export 节点逻辑，结果回写 state."""
        await self._advance_to_review()
        result = await workflow_runtime.export_workflow(PROJECT_ID)
        assert result["export_status"] == "done"
        assert result["export_storage_key"] == FAKE_EXPORT_KEY

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["export_storage_key"] == FAKE_EXPORT_KEY

    @pytest.mark.asyncio
    async def test_export_before_chapters_raises(self, memory_runtime, mock_node_deps) -> None:
        with pytest.raises(BizError):
            await workflow_runtime.export_workflow(PROJECT_ID)


class TestGuardAndInit:
    """后台任务异常可见性 + checkpointer 未初始化."""

    @pytest.mark.asyncio
    async def test_background_error_written_to_state(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """后台任务异常写入 state.error（可经 status 观测）."""

        async def boom(project_id, user_id):
            raise RuntimeError("模拟图执行崩溃")

        monkeypatch.setattr(workflow_runtime, "run_workflow", boom)
        task = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        await task

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert "模拟图执行崩溃" in status["error"]

    @pytest.mark.asyncio
    async def test_no_saver_raises_biz_error(self, memory_runtime) -> None:
        workflow_runtime.set_saver(None)
        with pytest.raises(BizError):
            await workflow_runtime.get_state(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_duplicate_start_rejected_and_slot_released(
        self, memory_runtime, monkeypatch
    ) -> None:
        """同一项目在途时重复 start 被拒（4009）；任务结束后槽位释放可再启动."""
        release = asyncio.Event()

        async def hang(project_id, user_id):
            await release.wait()
            return {}

        monkeypatch.setattr(workflow_runtime, "run_workflow", hang)
        task = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())

        with pytest.raises(BizError) as ei:
            workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        assert ei.value.code == 4009

        release.set()
        await task

        # 任务结束后槽位释放：可以再次启动
        monkeypatch.setattr(workflow_runtime, "run_workflow", AsyncMock(return_value={}))
        task2 = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        await task2

    @pytest.mark.asyncio
    async def test_init_checkpointer_closes_pool_when_setup_fails(self, monkeypatch) -> None:
        """pool.open() 成功后 saver.setup() 抛异常 → 已打开的 pool 被关闭，无连接泄漏.

        注：conftest 将 init_checkpointer 替换为跳过桩，这里调用其保留的原实现。
        """
        pool = MagicMock()
        pool.open = AsyncMock()
        pool.close = AsyncMock()
        monkeypatch.setattr(
            "langgraph.checkpoint.postgres.aio.AsyncConnectionPool", lambda *a, **k: pool
        )

        saver = MagicMock()
        saver.setup = AsyncMock(side_effect=RuntimeError("模拟 checkpointer 建表失败"))
        monkeypatch.setattr(
            workflow_runtime, "get_async_postgres_saver", lambda: lambda conn: saver
        )
        monkeypatch.setattr(workflow_runtime, "_saver", None, raising=False)
        monkeypatch.setattr(workflow_runtime, "_pool", None, raising=False)

        await workflow_runtime._init_checkpointer_impl()

        saver.setup.assert_awaited_once()
        pool.close.assert_awaited_once()
        assert workflow_runtime._saver is None
        assert workflow_runtime._pool is None
