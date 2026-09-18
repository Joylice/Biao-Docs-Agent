"""图集成测试 — LangGraph 全链路（InMemorySaver + mock LLM/DB/存储）.

对齐 SDD §6：parse → confirm(HITL) → outline → confirm_outline(HITL)
→ 章节循环 → review(HITL) → approved/feedback 分支 → export。
"""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents import nodes
from app.models.document import ScorePoint
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
    """模拟 AsyncSession：按目标模型返回预设行（BUG-2 适配：记录 commit）."""

    def __init__(self, rows_by_table: dict | None = None) -> None:
        self.rows_by_table = rows_by_table or {}
        self.added: list = []
        self.commit_count = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return FakeScalarResult(self.rows_by_table.get(entity, []))

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commit_count += 1

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
                    confirmed=True,  # 严格模式：仅已确认评分点进入大纲
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

    async def fake_check_consistency(*args, **kwargs) -> list:
        """不 mock 会真调 LLM → 超时挂起.

        刻意用 *args, **kwargs 而非精确签名：节点内的调用处在 except Exception
        保护之下，若桩的形参与真实函数不匹配会抛 TypeError 并**被静默吞成「无 issues」**
        （实测：2 参桩仍让全部用例通过 ⇒ 变异验证判为漏报）。签名正确性由
        TestMockStubSignatures 用 inspect.signature 独立守卫。
        """
        return []

    async def fake_review_chapters(*args, **kwargs) -> list:
        """auto_review_node 的副作用调用；不 mock 会真调 LLM → 超时挂起（同上，用通用签名）."""
        return []

    async def fake_is_mock_enabled(mock: bool | None = None) -> bool:
        """运行时配置读取会真连 PG → 挂起；测试固定为「非 mock」走确定性分支."""
        return False

    async def fake_get_runtime_config():
        """get_runtime_config 是多个入口的公共瓶颈（is_mock_enabled / resolve_llm_target）.

        虽内置 ``asyncio.timeout(5.0)``，但无 DB 环境下 psycopg connect 为静默阻塞，
        且 **_runtime_cache 只缓存成功/失败结果、不缓存"正在连接"状态** ⇒ 每个节点
        都重新付一次 5s 代价，多节点累积即超时。直接返回 None（走 env 回退分支）。
        """
        return None

    async def fake_get_route_cached(_stage_key: str):
        """阶段路由查询同样真连 PG；返回 None 即走旧逻辑（env 回退）."""
        return None

    monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
    monkeypatch.setattr(
        "app.services.llm.llm_service.call_llm_with_schema", fake_call_llm_with_schema
    )
    monkeypatch.setattr(
        "app.services.proposal.chapter_service.generate_chapter", fake_generate_chapter
    )
    monkeypatch.setattr(
        "app.services.proposal.review_service.rewrite_chapter", fake_rewrite_chapter
    )
    monkeypatch.setattr(
        "app.services.proposal.consistency_service.check_consistency",
        fake_check_consistency,
    )
    monkeypatch.setattr(
        "app.services.proposal.review_service.review_chapters", fake_review_chapters
    )
    monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.document.export_service.export_to_word", fake_export_to_word)

    # ── 外部工具取证（prefetch_external_evidence）─────────────────────────────
    # registry.get_definitions 走**自己的**（= app.core.database）session 工厂直连真实
    # PG —— 本机无 PG 时会在 psycopg connect 处无限阻塞，表现为整条 LangGraph 链路
    # 「静默挂起」（节点内 except 只在异常时降级，而这里是**阻塞**不是异常）。
    # 用空工厂 + 空绑定短路；prefetch 的 mock 短路逻辑照旧走 settings 判定。
    def empty_tool_factory():
        return FakeDB()

    monkeypatch.setattr(
        "app.services.infra.tools.registry.async_session_factory", empty_tool_factory
    )
    from app.services.infra.tools import registry

    registry.invalidate()
    # ── 运行时配置（is_mock_enabled / get_runtime_config）────────────────────
    # chat_with_tools 内部判 mock 时会读运行时配置；该函数虽有 asyncio.timeout(5.0)
    # 兜底，但无 DB 环境下 psycopg connect 为**静默丢包**式阻塞，逐个节点累积后
    # 整条链路远超测试超时。直接固定为「非 mock」以走确定性 mock 分支。
    monkeypatch.setattr("app.services.infra.settings.runtime.is_mock_enabled", fake_is_mock_enabled)
    monkeypatch.setattr(
        "app.services.infra.settings.runtime.get_runtime_config", fake_get_runtime_config
    )
    monkeypatch.setattr(
        "app.services.infra.settings.runtime._get_route_cached", fake_get_route_cached
    )


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
    async def test_review_feedback_loops_back(self, mock_deps, graph) -> None:
        """审阅反馈 → 回到 review interrupt 等待人工再次确认（rewrite 节点已移除）."""
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        initial = {"project_id": str(PROJECT_ID), "user_id": str(uuid.uuid4())}

        await graph.ainvoke(initial, config)
        await graph.ainvoke(Command(resume=True), config)
        result = await graph.ainvoke(Command(resume=True), config)
        assert result["__interrupt__"][0].value["type"] == "review_request"

        # 反馈 → 回到 review interrupt（不再触发 rewrite 节点）
        result = await graph.ainvoke(
            Command(resume={"action": "feedback", "feedback": {"1": "补充项目范围说明"}}),
            config,
        )
        assert result["__interrupt__"], "反馈后应再次停在审阅"
        assert result["__interrupt__"][0].value["type"] == "review_request"

        # 通过 → 导出
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


class TestMockStubSignatures:
    """被 mock 的函数签名守卫.

    🔴 动机（变异验证实测）：节点内的外部调用普遍包在 except Exception 里做**降级**，
    因此「桩的形参与真实函数不匹配」不会让测试失败 —— 只会抛 TypeError 后被静默吞成
    默认值（如「无 issues」）。实测把 fake_check_consistency 退回 2 参，**全部用例
    仍然通过** ⇒ 这是测试套件的固有盲区，必须用 inspect.signature 显式守卫，
    否则 S3 引入的「第 3 参 project_id」一旦被误删，测试会静默放行。
    """

    def test_check_consistency_accepts_project_id(self) -> None:
        import inspect

        from app.services.proposal.consistency_service import check_consistency

        params = list(inspect.signature(check_consistency).parameters)
        assert params == ["chapters", "outline", "project_id"], (
            f"check_consistency 签名漂移: {params}；节点按 3 参调用（project_id），"
            "漂移会因 except Exception 静默降级而无任何测试失败"
        )
        assert inspect.signature(check_consistency).parameters["project_id"].default is None

    def test_review_chapters_accepts_project_id(self) -> None:
        import inspect

        from app.services.proposal.review_service import review_chapters

        params = list(inspect.signature(review_chapters).parameters)
        assert params == ["chapters", "score_points", "project_id"], (
            f"review_chapters 签名漂移: {params}；auto_review_node 按 3 参调用"
        )
        assert inspect.signature(review_chapters).parameters["project_id"].default is None


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
