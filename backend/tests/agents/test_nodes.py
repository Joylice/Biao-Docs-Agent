"""节点函数单测 — mock LLM/DB/事件."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import nodes
from app.models.document import Document
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
    """模拟 AsyncSession（BUG-2 适配：记录 commit 调用次数）."""

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


# 阶段 E1 后 validate_node 为 async；参数比对隔离为无 issue
# （其自身单测在 test_param_check_service.py）
_NO_PARAM_ISSUE = patch(
    "app.services.proposal.param_check_service.check_chapter_params",
    AsyncMock(return_value=[]),
)


@pytest.fixture(autouse=True)
def _mock_llm_on(monkeypatch):
    """节点测试默认 mock 语义：阶段 F 工具分支仅真实模式触发，测试内可覆写为 False."""
    monkeypatch.setattr(
        "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=True)
    )


class TestValidateNode:
    """validate 节点规则校验."""

    @_NO_PARAM_ISSUE
    async def test_short_content_fails(self) -> None:
        state = {"current_chapter": "1", "chapters": {"1": "短"}, "validate_retries": 0}
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is False
        assert result["validate_retries"] == 1

    @_NO_PARAM_ISSUE
    async def test_long_content_passes(self) -> None:
        content = "# 章节\n\n" + "内容" * 200
        state = {"current_chapter": "1", "chapters": {"1": content}, "validate_retries": 0}
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is True

    @_NO_PARAM_ISSUE
    async def test_retries_capped(self) -> None:
        state = {
            "current_chapter": "1",
            "chapters": {"1": "短"},
            "validate_retries": nodes.MAX_VALIDATE_RETRIES,
        }
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is True  # 达到上限后放行

    @_NO_PARAM_ISSUE
    async def test_star_score_point_coverage(self) -> None:
        content = "# 章节\n\n" + "内容" * 200
        state = {
            "current_chapter": "1",
            "chapters": {"1": content},
            "validate_retries": 0,
            "score_points": [{"clause_no": "1", "item": "技术方案完整性", "is_star": True}],
        }
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is False  # 未覆盖 ★ 评分点

    async def test_param_mismatch_fails(self) -> None:
        """阶段 E1：参数比对 issue 走同一重试链路."""
        with patch(
            "app.services.proposal.param_check_service.check_chapter_params",
            AsyncMock(return_value=["参数不符评分点 2：要求不低于500路"]),
        ):
            content = "# 章节\n\n" + "内容" * 200
            state = {
                "current_chapter": "1",
                "chapters": {"1": content},
                "validate_retries": 0,
            }
            result = await nodes.validate_node(state)
            assert result["validation_ok"] is False
            assert result["validate_retries"] == 1

    @_NO_PARAM_ISSUE
    async def test_disqualification_high_hit_blocks(self) -> None:
        """阶段 H：命中已确认 high 废标条款 → 追加废标风险 issue + disqualification_risk 标记."""
        hits = [{"clause_no": "2.1", "title": "资质要求", "severity": "high"}]
        with patch(
            "app.services.proposal.disqualification_service.check_chapter_content",
            AsyncMock(return_value=hits),
        ):
            content = "# 章节\n\n" + "内容" * 200
            state = {
                "current_chapter": "1",
                "chapters": {"1": content},
                "validate_retries": 0,
                "project_id": str(PROJECT_ID),
            }
            result = await nodes.validate_node(state)
            assert result["validation_ok"] is False
            assert result["disqualification_risk"] is True

    @_NO_PARAM_ISSUE
    async def test_disqualification_no_hit_passes(self) -> None:
        """阶段 H：无废标命中 → 不追加 issue、不标记风险."""
        with patch(
            "app.services.proposal.disqualification_service.check_chapter_content",
            AsyncMock(return_value=[]),
        ):
            content = "# 章节\n\n" + "内容" * 200
            state = {
                "current_chapter": "1",
                "chapters": {"1": content},
                "validate_retries": 0,
                "project_id": str(PROJECT_ID),
            }
            result = await nodes.validate_node(state)
            assert result["validation_ok"] is True
            assert result.get("disqualification_risk") is not True

    @_NO_PARAM_ISSUE
    async def test_disqualification_check_error_degrades(self) -> None:
        """阶段 H：废标比对异常降级放行（不阻塞主链路）."""
        with patch(
            "app.services.proposal.disqualification_service.check_chapter_content",
            AsyncMock(side_effect=RuntimeError("db down")),
        ):
            content = "# 章节\n\n" + "内容" * 200
            state = {
                "current_chapter": "1",
                "chapters": {"1": content},
                "validate_retries": 0,
                "project_id": str(PROJECT_ID),
            }
            result = await nodes.validate_node(state)
            assert result["validation_ok"] is True


class TestRoutes:
    """条件路由函数."""

    def test_chapter_route_retry_on_invalid(self) -> None:
        state = {"validation_ok": False}
        assert nodes.chapter_route(state) == "write"

    def test_chapter_route_next_chapter(self) -> None:
        state = {
            "validation_ok": True,
            "outline": [{"chapter_no": "1"}, {"chapter_no": "2"}],
            "chapters": {"1": "x"},
        }
        assert nodes.chapter_route(state) == "retrieve"

    def test_chapter_route_integrate_when_done(self) -> None:
        state = {
            "validation_ok": True,
            "outline": [{"chapter_no": "1"}, {"chapter_no": "2"}],
            "chapters": {"1": "x", "2": "y"},
        }
        # 全部章节完成 → 先经全文一致性检查再整合
        assert nodes.chapter_route(state) == "consistency_check"

    def test_review_route_approved(self) -> None:
        assert nodes.review_route({"review_action": "approved"}) == "export"

    def test_review_route_feedback(self) -> None:
        assert nodes.review_route({"review_action": "feedback"}) == "rewrite"


class TestRetrieveNode:
    """RAG 检索节点."""

    @pytest.mark.asyncio
    async def test_retrieves_next_chapter_context(self, monkeypatch) -> None:
        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            # 接入 rerank 后召回池放宽到 RERANK_RECALL_K（精排后截断到 top_k=8）
            from app.services.llm import rag_service

            assert kwargs["top_k"] == rag_service.RERANK_RECALL_K
            return [
                type("Chunk", (), {"content": "素材A"})(),
                type("Chunk", (), {"content": "素材B"})(),
            ]

        def fake_session_factory():
            return FakeDB()

        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": ["背景"]}],
            "chapters": {},
        }
        result = await nodes.retrieve_node(state)
        assert result["current_chapter"] == "1"
        assert "素材A" in result["retrieved_context"]
        assert "素材B" in result["retrieved_context"]

    @pytest.mark.asyncio
    async def test_mounted_doc_ids_passed_to_retrieve(self, monkeypatch) -> None:
        """state 携带 mounted_doc_ids → 检索限定挂载文档（含字符串 UUID 转换）."""
        doc_a = uuid.uuid4()
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            captured["doc_ids"] = kwargs.get("doc_ids", "<missing>")
            return []

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_doc_ids": [str(doc_a)],  # checkpointer 序列化后为字符串
        }
        await nodes.retrieve_node(state)
        # 节点内 except 会吞掉 fake 内部断言，故捕获后外部断言
        assert captured["doc_ids"] == [doc_a]

    @pytest.mark.asyncio
    async def test_empty_mounted_doc_ids_means_no_mount(self, monkeypatch) -> None:
        """mounted_doc_ids=[] = 明确不挂载 → 传空列表（而非退化为项目全量检索）."""
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            captured["doc_ids"] = kwargs.get("doc_ids", "<missing>")
            return []

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_doc_ids": [],
        }
        await nodes.retrieve_node(state)
        assert captured["doc_ids"] == []

    @pytest.mark.asyncio
    async def test_mounted_kb_ids_resolved_to_doc_ids(self, monkeypatch) -> None:
        """mounted_kb_ids → 经 resolve_mount_doc_ids 展开库内素材传入检索."""
        kb_id = uuid.uuid4()
        doc_a = uuid.uuid4()
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            captured["doc_ids"] = kwargs.get("doc_ids", "<missing>")
            return []

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB({Document: [(doc_a,)]}))
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_kb_ids": [str(kb_id)],
        }
        await nodes.retrieve_node(state)
        assert captured["doc_ids"] == [doc_a]

    @pytest.mark.asyncio
    async def test_mounted_kb_and_doc_ids_union(self, monkeypatch) -> None:
        """库级 ∪ 文档级挂载并集去重后传入检索."""
        kb_id = uuid.uuid4()
        doc_kb, doc_direct = uuid.uuid4(), uuid.uuid4()
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            captured["doc_ids"] = kwargs.get("doc_ids", "<missing>")
            return []

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB({Document: [(doc_kb,)]}))
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_kb_ids": [str(kb_id)],
            "mounted_doc_ids": [str(doc_direct), str(doc_kb)],  # doc_kb 重复验证去重
        }
        await nodes.retrieve_node(state)
        assert captured["doc_ids"] == sorted([doc_kb, doc_direct], key=str)

    @pytest.mark.asyncio
    async def test_no_mounted_doc_ids_keeps_project_wide(self, monkeypatch) -> None:
        """state 无 mounted_doc_ids → doc_ids=None 保持项目全量检索（兼容存量）."""
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(**kwargs):
            captured["doc_ids"] = kwargs.get("doc_ids", "<missing>")
            return []

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
        }
        await nodes.retrieve_node(state)
        assert captured["doc_ids"] is None

    @pytest.mark.asyncio
    async def test_retrieve_failure_degrades(self, monkeypatch) -> None:
        async def fake_embedding(_text: str):
            raise RuntimeError("embedding 服务不可用")

        def fake_session_factory():
            return FakeDB()

        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_embedding)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
        }
        result = await nodes.retrieve_node(state)
        assert result["current_chapter"] == "1"
        assert result["retrieved_context"] == ""  # 降级无素材


class TestWriteNode:
    """章节撰写节点."""

    @pytest.mark.asyncio
    async def test_writes_and_persists(self, monkeypatch) -> None:
        async def fake_generate(**kwargs):
            assert kwargs["context"] == "素材上下文"
            assert kwargs["chapter"]["chapter_no"] == "1"
            return "# 章节内容\n\n" + "内容" * 100

        async def fake_publish(project_id: str, event: dict) -> None:
            events.append(event)

        dbs: list[FakeDB] = []

        def fake_session_factory():
            db = FakeDB()
            dbs.append(db)
            return db

        events: list[dict] = []
        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "outline": [{"chapter_no": "1", "title": "概述", "sections": ["背景"]}],
            "chapters": {},
            "score_points": [],
            "tech_requirements": [],
            "retrieved_context": "素材上下文",
        }
        result = await nodes.write_node(state)
        assert result["chapters"]["1"].startswith("# 章节内容")
        types = [e["type"] for e in events]
        assert "section_done" in types
        assert "progress" in types
        # BUG-2：章节落库块必须显式 commit，否则 proposal_sections 静默回滚
        assert dbs, "write_node 应打开 DB session"
        assert dbs[-1].commit_count >= 1, "章节落库后未 commit（数据将静默回滚）"

    @pytest.mark.asyncio
    async def test_streams_section_tokens_throttled(self, monkeypatch) -> None:
        """三期 S4：on_delta 节流发 section_token，delta 拼接 == 落库全文，section_done 收尾."""
        full_content = "A" * 30 + "B" * 30 + "C" * 5

        async def fake_generate(**kwargs):
            on_delta = kwargs.get("on_delta")
            assert on_delta is not None, "write_node 应传入 on_delta 开启流式"
            for piece in ("A" * 30, "B" * 30, "C" * 5):
                await on_delta(piece)
            return full_content

        events: list[dict] = []

        async def fake_publish(project_id: str, event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "outline": [{"chapter_no": "1", "title": "概述", "sections": ["背景"]}],
            "chapters": {},
            "score_points": [],
            "tech_requirements": [],
            "retrieved_context": "素材",
        }
        result = await nodes.write_node(state)
        assert result["chapters"]["1"] == full_content

        tokens = [e for e in events if e["type"] == "section_token"]
        assert len(tokens) >= 1, "应至少发布一条 section_token"
        assert all(t["chapter_no"] == "1" for t in tokens)
        assert "".join(t["delta"] for t in tokens) == full_content, "delta 拼接应等于全文"

        # section_done 在所有 section_token 之后，且携带全文（断线重连兜底）
        types = [e["type"] for e in events]
        assert types.index("section_done") > max(
            i for i, t in enumerate(types) if t == "section_token"
        )
        done = next(e for e in events if e["type"] == "section_done")
        assert done["content"] == full_content


class TestWriteNodeChapterSummaries:
    """章节间上下文 — write_node 注入 prior_summaries 并回存 chapter_summaries."""

    @pytest.mark.asyncio
    async def test_injects_prior_summaries_from_state(self, monkeypatch) -> None:
        """state 已有前序章节摘要 → 按大纲顺序传入 generate_chapter."""
        captured = {}

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            return "# 总体架构\n\n" + "内容" * 100

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", self._noop_publish())
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "2",
            "outline": [
                {"chapter_no": "1", "title": "项目概述", "sections": []},
                {"chapter_no": "2", "title": "总体架构", "sections": []},
            ],
            "chapters": {"1": "第一章全文"},
            "chapter_summaries": {"1": {"title": "项目概述", "summary": "介绍项目背景"}},
            "score_points": [],
            "tech_requirements": [],
            "retrieved_context": "素材",
        }
        await nodes.write_node(state)
        prior = captured["prior_summaries"]
        assert prior == [{"chapter_no": "1", "title": "项目概述", "summary": "介绍项目背景"}]

    @pytest.mark.asyncio
    async def test_stores_summary_after_generation(self, monkeypatch) -> None:
        """生成后提取 ≤200 字摘要存入 chapter_summaries（含标题）."""
        full_content = "# 总体架构\n\n" + "架" * 500

        async def fake_generate(**kwargs):
            return full_content

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", self._noop_publish())
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "2",
            "outline": [
                {"chapter_no": "1", "title": "项目概述", "sections": []},
                {"chapter_no": "2", "title": "总体架构", "sections": []},
            ],
            "chapters": {"1": "第一章全文"},
            "chapter_summaries": {"1": {"title": "项目概述", "summary": "介绍项目背景"}},
            "score_points": [],
            "tech_requirements": [],
            "retrieved_context": "素材",
        }
        result = await nodes.write_node(state)
        summaries = result["chapter_summaries"]
        # 前序摘要保留，本章新增
        assert summaries["1"]["summary"] == "介绍项目背景"
        assert summaries["2"]["title"] == "总体架构"
        assert summaries["2"]["summary"]
        assert len(summaries["2"]["summary"]) <= 200
        assert "#" not in summaries["2"]["summary"]

    @staticmethod
    def _noop_publish():
        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        return fake_publish


class TestWriteNodeCoverageMatrix:
    """评分点覆盖矩阵 — 未覆盖评分点注入补写指令，覆盖率随 progress 事件推送."""

    @pytest.mark.asyncio
    async def test_uncovered_points_injected_and_rate_pushed(self, monkeypatch) -> None:
        """confirmed SP 未被大纲覆盖 → supplement_points 传入生成，progress 事件带覆盖率."""
        captured = {}
        events: list[dict] = []

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            return "# 章节\n\n" + "内容" * 100

        async def fake_publish(_project_id: str, event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "outline": [
                {"chapter_no": "1", "title": "概述", "sections": [], "covered_clauses": ["1"]},
            ],
            "chapters": {},
            "score_points": [
                {"clause_no": "1", "item": "架构", "confirmed": True},
                {"clause_no": "2", "item": "安全", "confirmed": True},
            ],
            "tech_requirements": [],
            "retrieved_context": "素材",
        }
        await nodes.write_node(state)
        # 未覆盖评分点注入补写指令
        assert [sp["clause_no"] for sp in captured["supplement_points"]] == ["2"]
        # progress 事件携带覆盖率（1/2）
        progress_event = next(e for e in events if e["type"] == "progress")
        assert progress_event["coverage_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_full_coverage_no_supplement(self, monkeypatch) -> None:
        """全覆盖 → supplement_points 为空，覆盖率 1.0."""
        captured = {}

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            return "# 章节\n\n" + "内容" * 100

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(
            nodes,
            "publish_event",
            TestWriteNodeChapterSummaries._noop_publish(),
        )
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "outline": [
                {"chapter_no": "1", "title": "概述", "sections": [], "covered_clauses": ["1"]},
            ],
            "chapters": {},
            "score_points": [{"clause_no": "1", "item": "架构", "confirmed": True}],
            "tech_requirements": [],
            "retrieved_context": "素材",
        }
        await nodes.write_node(state)
        assert captured["supplement_points"] == []


class TestConsistencyCheckNode:
    """全文一致性检查节点 — integrate 前检查，可修复问题定向重写一轮，失败降级不阻塞."""

    @pytest.mark.asyncio
    async def test_no_issues_passes_through(self, monkeypatch) -> None:
        async def fake_check(chapters, outline):
            return []

        monkeypatch.setattr(
            "app.services.proposal.consistency_service.check_consistency", fake_check
        )
        state = {"project_id": str(PROJECT_ID), "chapters": {"1": "x"}, "outline": []}
        result = await nodes.consistency_check_node(state)
        assert result["consistency_issues"] == []
        assert "chapters" not in result  # 无问题不触发重写

    @pytest.mark.asyncio
    async def test_fixable_issues_trigger_one_rewrite_round(self, monkeypatch) -> None:
        """可修复 issues → 按章节聚合意见走 rewrite 链路，标记 consistency_retried."""
        rewritten: list[str] = []

        async def fake_check(chapters, outline):
            return [
                {
                    "chapter_no": "1",
                    "type": "terminology",
                    "description": "术语不一致",
                    "fixable": True,
                },
                {
                    "chapter_no": "1",
                    "type": "numbering",
                    "description": "编号断裂",
                    "fixable": True,
                },
            ]

        async def fake_rewrite(**kwargs):
            rewritten.append(kwargs["chapter_no"])
            return "修复后的内容" + "字" * 200

        monkeypatch.setattr(
            "app.services.proposal.consistency_service.check_consistency", fake_check
        )
        monkeypatch.setattr("app.services.proposal.review_service.rewrite_chapter", fake_rewrite)
        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", TestWriteNodeChapterSummaries._noop_publish())

        state = {
            "project_id": str(PROJECT_ID),
            "chapters": {"1": "原文"},
            "outline": [{"chapter_no": "1", "title": "概述"}],
        }
        result = await nodes.consistency_check_node(state)
        assert rewritten == ["1"]  # 同章多 issue 聚合为一轮重写
        assert result["consistency_retried"] is True
        assert result["chapters"]["1"] == "修复后的内容" + "字" * 200

    @pytest.mark.asyncio
    async def test_retried_issues_degrade_to_warning(self, monkeypatch) -> None:
        """已重写过一轮仍有问题 → 发 warning 事件，不再重写、不阻塞导出."""
        events: list[dict] = []

        async def fake_check(chapters, outline):
            return [{"chapter_no": "1", "description": "重复段落", "fixable": True}]

        async def fake_rewrite(**kwargs):
            raise AssertionError("已重试过不应再次重写")

        async def fake_publish(_project_id: str, event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(
            "app.services.proposal.consistency_service.check_consistency", fake_check
        )
        monkeypatch.setattr("app.services.proposal.review_service.rewrite_chapter", fake_rewrite)
        monkeypatch.setattr(nodes, "publish_event", fake_publish)

        state = {
            "project_id": str(PROJECT_ID),
            "chapters": {"1": "原文"},
            "outline": [],
            "consistency_retried": True,
        }
        result = await nodes.consistency_check_node(state)
        assert len(result["consistency_issues"]) == 1
        assert any(e["type"] == "warning" for e in events)

    @pytest.mark.asyncio
    async def test_check_failure_degrades_not_blocking(self, monkeypatch) -> None:
        """检查异常 → 降级无问题继续流程（不阻塞导出）."""

        async def fake_check(chapters, outline):
            raise RuntimeError("LLM 不可用")

        monkeypatch.setattr(
            "app.services.proposal.consistency_service.check_consistency", fake_check
        )
        state = {"project_id": str(PROJECT_ID), "chapters": {"1": "x"}, "outline": []}
        result = await nodes.consistency_check_node(state)
        assert result["consistency_issues"] == []


class TestNodeCommits:
    """BUG-2：节点写库块在 session 退出前显式 commit."""

    @pytest.mark.asyncio
    async def test_generate_outline_node_commits(self, monkeypatch) -> None:
        """大纲落库（proposal_skeletons + workflow）显式提交."""

        async def fake_llm(**kwargs) -> dict:
            return {"chapters": [{"chapter_no": "1", "title": "概述", "sections": ["背景"]}]}

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        dbs: list[FakeDB] = []

        def fake_session_factory():
            db = FakeDB()
            dbs.append(db)
            return db

        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_llm)

        state = {
            "project_id": str(PROJECT_ID),
            "score_points": [{"clause_no": "1", "item": "技术方案完整性", "is_star": False}],
            "tech_requirements": [],
        }
        result = await nodes.generate_outline_node(state)
        assert "error" not in result
        assert result["outline"], "mock LLM 应返回大纲"
        assert dbs, "generate_outline_node 应打开 DB session"
        # 阶段6 后首个 session 为项目上下文只读查询；写库 session 含 skeleton 且必须 commit
        write_db = next(
            (
                db
                for db in dbs
                if any(obj.__class__.__name__ == "ProposalSkeleton" for obj in db.added)
            ),
            None,
        )
        assert write_db is not None, "大纲应写入 proposal_skeletons"
        assert write_db.commit_count >= 1, "大纲落库后未 commit（skeleton 将静默回滚）"


class TestOutlineNodeCoveredClauses:
    """大纲节点增强：每章节标注覆盖评分点（covered_clauses）."""

    @pytest.mark.asyncio
    async def test_schema_requires_covered_clauses(self, monkeypatch) -> None:
        """大纲 schema 应要求 covered_clauses 字段，确保评分点可追溯."""
        from app.services.llm import llm_service

        captured: dict = {}

        async def fake_llm(**kwargs) -> dict:
            captured["response_format"] = kwargs.get("response_format")
            return {
                "chapters": [
                    {
                        "chapter_no": "1",
                        "title": "概述",
                        "sections": ["背景"],
                        "covered_clauses": ["1"],
                    }
                ]
            }

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr(llm_service, "call_llm_with_schema", fake_llm)

        state = {
            "project_id": str(PROJECT_ID),
            "score_points": [{"clause_no": "1", "item": "技术方案"}],
            "tech_requirements": [],
        }
        result = await nodes.generate_outline_node(state)
        assert "error" not in result
        schema = (captured["response_format"] or {}).get("json_schema", {}).get("schema", {})
        chap_item = schema.get("properties", {}).get("chapters", {}).get("items", {})
        assert "covered_clauses" in chap_item.get("properties", {})
        assert "covered_clauses" in chap_item.get("required", [])

    @pytest.mark.asyncio
    async def test_outline_carries_covered_clauses_to_skeleton(self, monkeypatch) -> None:
        """LLM 返回的 covered_clauses 应透传到 outline 并写入 proposal_skeletons."""
        from app.models.proposal import ProposalSkeleton

        async def fake_llm(**kwargs) -> dict:
            return {
                "chapters": [
                    {
                        "chapter_no": "1",
                        "title": "技术方案",
                        "sections": ["架构"],
                        "covered_clauses": ["4.2.1", "4.2.2"],
                    }
                ]
            }

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        db = FakeDB()

        monkeypatch.setattr(nodes, "async_session_factory", lambda: db)
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_llm)

        state = {
            "project_id": str(PROJECT_ID),
            "score_points": [{"clause_no": "4.2.1", "item": "架构"}],
            "tech_requirements": [],
        }
        result = await nodes.generate_outline_node(state)
        assert result["outline"][0]["covered_clauses"] == ["4.2.1", "4.2.2"]
        skeleton = next(o for o in db.added if isinstance(o, ProposalSkeleton))
        assert skeleton.tree[0]["covered_clauses"] == ["4.2.1", "4.2.2"], (
            "covered_clauses 应随 tree 持久化到 proposal_skeletons"
        )


class TestOutlineProjectContextAndIsolation:
    """阶段6：大纲注入项目上下文（名称/标书号/行业）+ 项目间隔离回归."""

    @staticmethod
    def _project(project_id) -> "Project":
        return Project(
            id=project_id,
            name="智慧水务一体化平台项目",
            tender_no="ZB-2026-001",
            industry="智慧水务",
            owner_id=uuid.uuid4(),
        )

    @pytest.mark.asyncio
    async def test_outline_prompt_injects_project_context(self, monkeypatch) -> None:
        """大纲提示词应含项目名称/标书号/行业，且系统提示词要求结合项目具体化.

        2026-08-26 单一数据源重构：generate_outline 改纯 state 读，项目上下文
        （project_name/tender_no/industry）由 parse/refresh_context 节点写入 state，
        本测试直接在 state 中传这些字段，FakeDB 仅作 skeleton 落库。
        """
        from app.models.project import Project
        from app.services.llm import llm_service

        captured: dict = {}

        async def fake_llm(**kwargs) -> dict:
            captured["system_prompt"] = kwargs.get("system_prompt")
            captured["user_prompt"] = kwargs.get("user_prompt")
            return {
                "chapters": [
                    {"chapter_no": "1", "title": "概述", "sections": [], "covered_clauses": []}
                ]
            }

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        # FakeDB 仅作 skeleton 落库，不再提供项目上下文（纯 state 读）
        monkeypatch.setattr(
            nodes, "async_session_factory", lambda: FakeDB({Project: [self._project(PROJECT_ID)]})
        )
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr(llm_service, "call_llm_with_schema", fake_llm)

        # state 直接传项目上下文（parse/refresh_context 已写入）
        state = {
            "project_id": str(PROJECT_ID),
            "project_name": "智慧水务一体化平台项目",
            "tender_no": "ZB-2026-001",
            "industry": "智慧水务",
            "score_points": [{"clause_no": "1", "item": "技术方案"}],
            "tech_requirements": [{"seq": 1, "description": "巡检管理", "category": "软件"}],
        }
        result = await nodes.generate_outline_node(state)
        assert "error" not in result
        assert "智慧水务一体化平台项目" in captured["user_prompt"]
        assert "ZB-2026-001" in captured["user_prompt"]
        assert "智慧水务" in captured["user_prompt"]
        # 系统提示词强化：章节标题必须结合项目具体化，禁止通用模板
        assert "具体化" in captured["system_prompt"]

    @pytest.mark.asyncio
    async def test_context_missing_degrades_not_blocking(self, monkeypatch) -> None:
        """项目不存在 → 降级照常生成大纲（不阻塞）."""

        async def fake_llm(**kwargs) -> dict:
            return {
                "chapters": [
                    {"chapter_no": "1", "title": "概述", "sections": [], "covered_clauses": []}
                ]
            }

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_llm)

        state = {"project_id": str(PROJECT_ID), "score_points": [], "tech_requirements": []}
        result = await nodes.generate_outline_node(state)
        assert "error" not in result
        assert result["outline"]

    @pytest.mark.asyncio
    async def test_two_projects_outline_isolated(self, monkeypatch) -> None:
        """双项目先后生成大纲：各自按 project_id 落库互不串扰."""
        from app.models.proposal import ProposalSkeleton

        pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
        dbs: list[FakeDB] = []

        def factory():
            db = FakeDB()
            dbs.append(db)
            return db

        async def fake_llm(**kwargs) -> dict:
            return {
                "chapters": [
                    {"chapter_no": "1", "title": "概述", "sections": [], "covered_clauses": []}
                ]
            }

        async def fake_publish(_project_id: str, _event: dict) -> None:
            pass

        monkeypatch.setattr(nodes, "async_session_factory", factory)
        monkeypatch.setattr(nodes, "publish_event", fake_publish)
        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_llm)

        for pid in (pid_a, pid_b):
            result = await nodes.generate_outline_node(
                {"project_id": str(pid), "score_points": [], "tech_requirements": []}
            )
            assert "error" not in result

        skeletons = [o for db in dbs for o in db.added if isinstance(o, ProposalSkeleton)]
        assert {s.project_id for s in skeletons} == {pid_a, pid_b}, (
            "每个项目的大纲应各自落到自己的 project_id，不得串扰"
        )


class TestWriteNodeToolPreflight:
    """阶段 F：write_node 工具前置补充检索（仅真实模式，mock/异常降级原上下文）."""

    def _state(self) -> dict:
        return {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "score_points": [],
            "tech_requirements": [],
            "retrieved_context": "基础素材",
        }

    def _patch_common(self, monkeypatch, captured: dict) -> None:
        async def fake_generate(**kwargs):
            captured.update(kwargs)
            return "# 章节\n\n" + "内容" * 100

        monkeypatch.setattr(nodes, "async_session_factory", lambda: FakeDB())
        monkeypatch.setattr(nodes, "publish_event", AsyncMock())
        monkeypatch.setattr("app.services.proposal.chapter_service.generate_chapter", fake_generate)

    @pytest.mark.asyncio
    async def test_mock_mode_skips_preflight(self, monkeypatch) -> None:
        """mock 模式行为与现版本等价：preflight 不触发，上下文原样传入."""
        captured: dict = {}
        self._patch_common(monkeypatch, captured)
        preflight = AsyncMock(return_value="不应被调用")
        monkeypatch.setattr("app.agents.tools.write_tool_preflight", preflight)
        await nodes.write_node(self._state())
        preflight.assert_not_called()
        assert captured["context"] == "基础素材"

    @pytest.mark.asyncio
    async def test_real_mode_enriches_context(self, monkeypatch) -> None:
        """真实模式：preflight 返回的补充素材拼入 generate_chapter 上下文."""
        captured: dict = {}
        self._patch_common(monkeypatch, captured)
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            "app.agents.tools.write_tool_preflight",
            AsyncMock(return_value="基础素材\n\n---\n\n补充素材"),
        )
        await nodes.write_node(self._state())
        assert "补充素材" in captured["context"]

    @pytest.mark.asyncio
    async def test_preflight_failure_degrades(self, monkeypatch) -> None:
        """preflight 异常降级：不阻塞生成，上下文保持原样."""
        captured: dict = {}
        self._patch_common(monkeypatch, captured)
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            "app.agents.tools.write_tool_preflight", AsyncMock(side_effect=RuntimeError("boom"))
        )
        result = await nodes.write_node(self._state())
        assert captured["context"] == "基础素材"
        assert result["chapters"]["1"]


class TestValidateNodeToolRecheck:
    """阶段 F：validate_node 工具辅助取证复核（仅真实模式且存在 issues）."""

    @_NO_PARAM_ISSUE
    @pytest.mark.asyncio
    async def test_recheck_filters_false_positive(self, monkeypatch) -> None:
        """真实模式：复核后 issues 清空 → 校验通过."""
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        monkeypatch.setattr("app.agents.tools.validate_tool_recheck", AsyncMock(return_value=[]))
        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "chapters": {"1": "短"},
            "validate_retries": 0,
        }
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is True

    @_NO_PARAM_ISSUE
    @pytest.mark.asyncio
    async def test_mock_mode_skips_recheck(self, monkeypatch) -> None:
        """mock 模式：复核不触发，规则 issues 保持."""
        recheck = AsyncMock(return_value=[])
        monkeypatch.setattr("app.agents.tools.validate_tool_recheck", recheck)
        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "chapters": {"1": "短"},
            "validate_retries": 0,
        }
        result = await nodes.validate_node(state)
        recheck.assert_not_called()
        assert result["validation_ok"] is False

    @_NO_PARAM_ISSUE
    @pytest.mark.asyncio
    async def test_recheck_failure_keeps_issues(self, monkeypatch) -> None:
        """复核异常降级：保留原 issues，校验仍失败."""
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            "app.agents.tools.validate_tool_recheck", AsyncMock(side_effect=RuntimeError("boom"))
        )
        state = {
            "project_id": str(PROJECT_ID),
            "current_chapter": "1",
            "chapters": {"1": "短"},
            "validate_retries": 0,
        }
        result = await nodes.validate_node(state)
        assert result["validation_ok"] is False
