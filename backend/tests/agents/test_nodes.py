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
    """模拟 AsyncSession."""

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

        def fake_session_factory():
            return FakeDB()

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
