"""节点函数单测 — mock LLM/DB/事件."""

import uuid

import pytest

from app.agents import nodes

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


class TestValidateNode:
    """validate 节点规则校验."""

    def test_short_content_fails(self) -> None:
        state = {"current_chapter": "1", "chapters": {"1": "短"}, "validate_retries": 0}
        result = nodes.validate_node(state)
        assert result["validation_ok"] is False
        assert result["validate_retries"] == 1

    def test_long_content_passes(self) -> None:
        content = "# 章节\n\n" + "内容" * 200
        state = {"current_chapter": "1", "chapters": {"1": content}, "validate_retries": 0}
        result = nodes.validate_node(state)
        assert result["validation_ok"] is True

    def test_retries_capped(self) -> None:
        state = {
            "current_chapter": "1",
            "chapters": {"1": "短"},
            "validate_retries": nodes.MAX_VALIDATE_RETRIES,
        }
        result = nodes.validate_node(state)
        assert result["validation_ok"] is True  # 达到上限后放行

    def test_star_score_point_coverage(self) -> None:
        content = "# 章节\n\n" + "内容" * 200
        state = {
            "current_chapter": "1",
            "chapters": {"1": content},
            "validate_retries": 0,
            "score_points": [{"clause_no": "1", "item": "技术方案完整性", "is_star": True}],
        }
        result = nodes.validate_node(state)
        assert result["validation_ok"] is False  # 未覆盖 ★ 评分点


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
        assert nodes.chapter_route(state) == "integrate"

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
            assert kwargs["top_k"] == 8
            return [
                type("Chunk", (), {"content": "素材A"})(),
                type("Chunk", (), {"content": "素材B"})(),
            ]

        def fake_session_factory():
            return FakeDB()

        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)

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
        monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)

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
        monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)

        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_doc_ids": [],
        }
        await nodes.retrieve_node(state)
        assert captured["doc_ids"] == []

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
        monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
        monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)

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
        monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)

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
        monkeypatch.setattr("app.services.chapter_service.generate_chapter", fake_generate)

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
        monkeypatch.setattr("app.services.chapter_service.generate_chapter", fake_generate)

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
        monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", fake_llm)

        state = {
            "project_id": str(PROJECT_ID),
            "score_points": [{"clause_no": "1", "item": "技术方案完整性", "is_star": False}],
            "tech_requirements": [],
        }
        result = await nodes.generate_outline_node(state)
        assert "error" not in result
        assert result["outline"], "mock LLM 应返回大纲"
        assert dbs, "generate_outline_node 应打开 DB session"
        assert dbs[0].commit_count >= 1, "大纲落库后未 commit（skeleton 将静默回滚）"
        # 大纲确实写入 session
        assert any(obj.__class__.__name__ == "ProposalSkeleton" for obj in dbs[0].added), (
            "大纲应写入 proposal_skeletons"
        )


class TestOutlineNodeCoveredClauses:
    """大纲节点增强：每章节标注覆盖评分点（covered_clauses）."""

    @pytest.mark.asyncio
    async def test_schema_requires_covered_clauses(self, monkeypatch) -> None:
        """大纲 schema 应要求 covered_clauses 字段，确保评分点可追溯."""
        from app.services import llm_service

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
        monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", fake_llm)

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
