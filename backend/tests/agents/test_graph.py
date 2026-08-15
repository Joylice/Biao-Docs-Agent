"""图集成测试 — LangGraph 全链路（InMemorySaver + mock LLM/DB/存储）.

对齐 SDD §6：parse → confirm(HITL) → outline → confirm_outline(HITL)
→ 章节循环 → review(HITL) → approved/feedback 分支 → export。
"""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents import nodes
from app.models.document import ScorePoint, TechRequirement
from app.models.project import Project

PROJECT_ID = uuid.uuid4()


class FakeScalarResult:
    """模拟 SQLAlchemy execute 结果."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """模拟 AsyncSession：按目标模型返回预设行."""

    def __init__(self, rows_by_table: dict | None = None) -> None:
        self.rows_by_table = rows_by_table or {}
        self.added: list = []

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return FakeScalarResult(self.rows_by_table.get(entity, []))

    async def flush(self) -> None:
        pass

    def add(self, obj) -> None:
        self.added.append(obj)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


def make_fake_db() -> FakeDB:
    """构造含解析结果的工作流 DB mock."""
    return FakeDB(
        {
            Project: [
                Project(
                    id=PROJECT_ID,
                    name="测试项目",
                    tender_no="TN-2026-001",
                    owner_id=uuid.uuid4(),
                )
            ],
            ScorePoint: [
                ScorePoint(
                    id=uuid.uuid4(),
                    project_id=PROJECT_ID,
                    doc_id=uuid.uuid4(),
                    clause_no="1",
                    item="技术方案完整性",
                    score=10,
                    criteria="方案完整",
                    is_star=True,
                )
            ],
            TechRequirement: [
                TechRequirement(
                    id=uuid.uuid4(),
                    project_id=PROJECT_ID,
                    doc_id=uuid.uuid4(),
                    seq=1,
                    description="支持高可用",
                    category="架构",
                    is_mandatory=True,
                )
            ],
        }
    )


@pytest.fixture
def mock_deps(monkeypatch):
    """统一 mock 节点外部依赖（LLM/DB/RAG/存储/事件）."""

    async def fake_publish_event(_project_id: str, _event: dict) -> None:
        pass

    def fake_session_factory():
        return make_fake_db()

    async def fake_call_llm_with_schema(**kwargs) -> dict:
        return {
            "chapters": [
                {"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]},
                {"chapter_no": "2", "title": "技术方案", "sections": ["架构", "实现"]},
            ]
        }

    async def fake_generate_chapter(**kwargs) -> str:
        return "# 章节内容\n\n这是一段足够长的测试章节内容，用于通过字数校验。\n" * 8

    async def fake_rewrite_chapter(**kwargs) -> str:
        return "# 重写后的章节\n\n根据审阅意见修改后的内容，长度满足校验要求。\n" * 8

    async def fake_get_embedding(_text: str):
        return []

    async def fake_retrieve_similar(**kwargs):
        return []

    async def fake_export_to_word(**kwargs) -> str:
        return f"{PROJECT_ID}/export/test.docx"

    monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
    monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", fake_call_llm_with_schema)
    monkeypatch.setattr("app.services.chapter_service.generate_chapter", fake_generate_chapter)
    monkeypatch.setattr("app.services.review_service.rewrite_chapter", fake_rewrite_chapter)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.export_service.export_to_word", fake_export_to_word)


@pytest.fixture
def graph():
    from app.agents.graph import compile_workflow

    return compile_workflow(checkpointer=InMemorySaver())


class TestWorkflowInterrupt:
    """HITL 中断与恢复全链路."""

    @pytest.mark.asyncio
    async def test_full_flow_with_interrupts(self, mock_deps, graph) -> None:
        """parse → confirm → outline → confirm → 章节 → review → export."""
        config = {"configurable": {"thread_id": str(PROJECT_ID)}}
        initial = {"project_id": str(PROJECT_ID), "user_id": str(uuid.uuid4())}

        # 1. 停在 confirm_score_points
        result = await graph.ainvoke(initial, config)
        assert result["__interrupt__"], "应停在评分点确认"
        assert result["__interrupt__"][0].value["type"] == "confirm_score_points"
        assert result["current_phase"] == "confirm"

        # 2. 确认评分点 → 停在 confirm_outline
        result = await graph.ainvoke(Command(resume=True), config)
        assert result["__interrupt__"], "应停在大纲确认"
        assert result["__interrupt__"][0].value["type"] == "confirm_outline"
        assert len(result["outline"]) == 2

        # 3. 确认大纲 → 生成全部章节 → 停在 review
        result = await graph.ainvoke(Command(resume=True), config)
        assert result["__interrupt__"], "应停在审阅"
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert set(result["chapters"].keys()) == {"1", "2"}
        assert result["current_phase"] == "review"

        # 4. 审阅通过 → 导出完成
        result = await graph.ainvoke(Command(resume={"action": "approved"}), config)
        assert result["export_status"] == "done"
        assert result["current_phase"] == "done"
        assert result["progress"] == 1.0

    @pytest.mark.asyncio
    async def test_review_feedback_rewrites(self, mock_deps, graph) -> None:
        """审阅反馈 → 重写 → 再次中断审阅."""
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        initial = {"project_id": str(PROJECT_ID), "user_id": str(uuid.uuid4())}

        await graph.ainvoke(initial, config)
        await graph.ainvoke(Command(resume=True), config)
        result = await graph.ainvoke(Command(resume=True), config)
        assert result["__interrupt__"][0].value["type"] == "review_request"

        # 反馈重写章节 1
        result = await graph.ainvoke(
            Command(resume={"action": "feedback", "feedback": {"1": "补充项目范围说明"}}),
            config,
        )
        assert result["__interrupt__"], "重写后应再次停在审阅"
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert "重写后的章节" in result["chapters"]["1"]

        # 重写后通过 → 导出
        result = await graph.ainvoke(Command(resume={"action": "approved"}), config)
        assert result["export_status"] == "done"

    @pytest.mark.asyncio
    async def test_workflow_state_persisted(self, mock_deps, graph) -> None:
        """中断后状态可从 checkpointer 恢复（thread 内状态持久化）."""
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        initial = {"project_id": str(PROJECT_ID), "user_id": str(uuid.uuid4())}

        await graph.ainvoke(initial, config)

        # 新连接同一 thread → 从断点继续
        result = await graph.ainvoke(Command(resume=True), config)
        assert result["__interrupt__"][0].value["type"] == "confirm_outline"


class TestWorkflowErrors:
    """异常路径."""

    @pytest.mark.asyncio
    async def test_no_score_points_aborts(self, monkeypatch, graph) -> None:
        """项目无评分点时流程报错."""

        def empty_session_factory():
            return FakeDB()  # 无任何数据

        monkeypatch.setattr(nodes, "async_session_factory", empty_session_factory)
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = await graph.ainvoke(
            {"project_id": str(PROJECT_ID), "user_id": str(uuid.uuid4())}, config
        )
        assert "无评分点" in result.get("error", "")
        assert result.get("current_phase") == "init"
