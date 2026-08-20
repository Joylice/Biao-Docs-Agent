"""阶段 F：LangGraph Tool Calling 工具注册表测试（SDD §6.3 四工具）."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import tools

PROJECT_ID = str(uuid.uuid4())


class FakeScalarResult:
    """模拟 SQLAlchemy execute 结果（scalars().all()）."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """模拟 AsyncSession（只读块）."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def execute(self, stmt):
        return FakeScalarResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


class TestRegistry:
    """工具注册表：四工具 schema + OpenAI tools 封装."""

    def test_four_tools_registered(self) -> None:
        assert set(tools.TOOL_SCHEMAS) == {
            "kb_search",
            "get_score_points",
            "list_sections",
            "update_glossary",
        }

    def test_definitions_openai_shape(self) -> None:
        defs = tools.get_tool_definitions(["kb_search", "get_score_points"])
        assert len(defs) == 2
        assert all(d["type"] == "function" for d in defs)
        assert defs[0]["function"]["name"] == "kb_search"
        assert "query" in defs[0]["function"]["parameters"]["properties"]


class TestKbSearch:
    """kb_search：mock 确定性分支 + 真实分支封装 rag_service."""

    @pytest.mark.asyncio
    async def test_mock_branch_deterministic(self) -> None:
        with patch.object(tools.settings_service, "is_mock_enabled", AsyncMock(return_value=True)):
            first = await tools.kb_search(PROJECT_ID, "微服务架构")
            second = await tools.kb_search(PROJECT_ID, "微服务架构")
        assert first == second and first, "mock 分支须确定性返回"
        assert "微服务架构" in first[0]["content"]

    @pytest.mark.asyncio
    async def test_real_branch_wraps_rag(self) -> None:
        hit = SimpleNamespace(content="素材内容", page_no=2, score=0.9)
        with (
            patch.object(tools.settings_service, "is_mock_enabled", AsyncMock(return_value=False)),
            patch("app.services.rag_service.get_embedding", AsyncMock(return_value=object())),
            patch(
                "app.services.rag_service.retrieve_with_rerank", AsyncMock(return_value=[hit])
            ),
            patch.object(tools, "async_session_factory", lambda: FakeDB([])),
        ):
            rows = await tools.kb_search(PROJECT_ID, "q")
        assert rows == [{"doc_title": "", "content": "素材内容", "page_no": 2, "score": 0.9}]


class TestGetScorePoints:
    """get_score_points：读当前项目评分点."""

    @pytest.mark.asyncio
    async def test_reads_from_db(self) -> None:
        sp = SimpleNamespace(clause_no="1", item="架构", score=6.0, criteria="完整", is_star=True)
        with patch.object(tools, "async_session_factory", lambda: FakeDB([sp])):
            rows = await tools.get_score_points(PROJECT_ID)
        assert rows[0]["clause_no"] == "1"
        assert rows[0]["item"] == "架构"
        assert rows[0]["is_star"] is True


class TestListSections:
    """list_sections：读已生成章节摘要."""

    @pytest.mark.asyncio
    async def test_returns_summaries(self) -> None:
        sec = SimpleNamespace(
            section_id="1.1", title="背景", content_md="# 背景\n\n" + "内容" * 200
        )
        with patch.object(tools, "async_session_factory", lambda: FakeDB([sec])):
            rows = await tools.list_sections(PROJECT_ID)
        assert rows[0]["section_id"] == "1.1"
        assert rows[0]["title"] == "背景"
        assert rows[0]["summary"] and len(rows[0]["summary"]) <= 200


class TestUpdateGlossary:
    """update_glossary：纯函数合并术语表（同名覆盖）."""

    def test_merge_and_dedupe(self) -> None:
        glossary = [{"term": "K8s", "canonical": "Kubernetes", "desc": ""}]
        merged = tools.update_glossary(glossary, "K8s", "Kubernetes 集群", "容器编排")
        assert len(merged) == 1
        assert merged[0]["canonical"] == "Kubernetes 集群"
        assert merged[0]["desc"] == "容器编排"

    def test_append_new_term(self) -> None:
        merged = tools.update_glossary([], "RAG", "检索增强生成", "")
        assert merged == [{"term": "RAG", "canonical": "检索增强生成", "desc": ""}]


class TestExecuteTool:
    """execute_tool：按名调度 + 未知工具报错."""

    @pytest.mark.asyncio
    async def test_dispatch_kb_search(self) -> None:
        with patch.object(tools.settings_service, "is_mock_enabled", AsyncMock(return_value=True)):
            result = await tools.execute_tool("kb_search", {"query": "安全"}, PROJECT_ID)
        assert result and "安全" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_dispatch_update_glossary_uses_state_glossary(self) -> None:
        result = await tools.execute_tool(
            "update_glossary",
            {"term": "AI", "canonical": "人工智能"},
            PROJECT_ID,
            glossary=[{"term": "AI", "canonical": "AI", "desc": ""}],
        )
        assert result == [{"term": "AI", "canonical": "人工智能", "desc": ""}]

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="未知工具"):
            await tools.execute_tool("web_search", {}, PROJECT_ID)


class TestPreflightAndRecheck:
    """write 前置补充检索 / validate 辅助取证（chat_with_tools 之上的语义封装）."""

    @pytest.mark.asyncio
    async def test_preflight_appends_kb_hits(self) -> None:
        calls = [
            {
                "name": "kb_search",
                "arguments": {"query": "q"},
                "result": json.dumps([{"content": "补充素材A"}], ensure_ascii=False),
            }
        ]
        with patch(
            "app.services.llm_service.chat_with_tools",
            AsyncMock(return_value=("无需补充", calls)),
        ):
            ctx = await tools.write_tool_preflight(PROJECT_ID, "总体架构", "基础素材")
        assert "基础素材" in ctx and "补充素材A" in ctx

    @pytest.mark.asyncio
    async def test_preflight_no_calls_returns_base(self) -> None:
        with patch(
            "app.services.llm_service.chat_with_tools", AsyncMock(return_value=("无需补充", []))
        ):
            ctx = await tools.write_tool_preflight(PROJECT_ID, "总体架构", "基础素材")
        assert ctx == "基础素材"

    @pytest.mark.asyncio
    async def test_recheck_keeps_confirmed_issues(self) -> None:
        issues = ["字数不足（10 < 200）", "误报问题"]
        with patch(
            "app.services.llm_service.chat_with_tools",
            AsyncMock(return_value=('{"keep": ["字数不足（10 < 200）"]}', [])),
        ):
            kept = await tools.validate_tool_recheck(PROJECT_ID, "1", "正文", issues, [])
        assert kept == ["字数不足（10 < 200）"]

    @pytest.mark.asyncio
    async def test_recheck_invalid_json_keeps_all(self) -> None:
        issues = ["问题A"]
        with patch(
            "app.services.llm_service.chat_with_tools", AsyncMock(return_value=("解析不了", []))
        ):
            kept = await tools.validate_tool_recheck(PROJECT_ID, "1", "正文", issues, [])
        assert kept == issues
