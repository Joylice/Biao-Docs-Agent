"""E2 术语表机制（glossary）测试 — 解析抽取 → 落库 meta → 注入生成 → 整合统一.

链路：parse LLM schema 增 glossary → save_parse_result 写 documents.meta.glossary
→ parse_tender_node 载入 state.glossary → chapter.yaml {glossary} 段注入
→ integrate_node 统一术语（mock 直通，真实模式规则替换）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.document import parse_service
from app.services.document.parse_service import ParsedTender
from app.services.proposal import glossary_service


class TestParseSchemaGlossary:
    @pytest.mark.asyncio
    async def test_schema_contains_glossary_and_parse_result(self, monkeypatch) -> None:
        """parse LLM schema 含 glossary 数组（term/canonical/desc），结果透传."""
        captured: dict = {}

        async def fake_call(system_prompt, user_prompt, response_format=None, mock=None):
            captured["schema"] = response_format["json_schema"]["schema"]
            return {
                "score_points": [{"clause_no": "1", "item": "方案"}],
                "glossary": [{"term": "AI", "canonical": "人工智能", "desc": "统一用全称"}],
            }

        from app.services.llm import llm_service

        monkeypatch.setattr(llm_service, "call_llm_with_schema", fake_call)
        parsed = await parse_service.parse_tender_with_llm("招标正文")

        props = captured["schema"]["properties"]
        assert "glossary" in props
        item_required = set(props["glossary"]["items"]["required"])
        assert {"term", "canonical"} <= item_required
        assert parsed.glossary == [{"term": "AI", "canonical": "人工智能", "desc": "统一用全称"}]

    def test_parsed_tender_glossary_default(self) -> None:
        parsed = ParsedTender(score_points=[], tech_requirements=[])
        assert parsed.glossary == []


class TestSaveGlossaryToMeta:
    @pytest.mark.asyncio
    async def test_save_writes_glossary_to_doc_meta(self) -> None:
        doc_id = uuid.uuid4()
        project_id = uuid.uuid4()
        from app.models.document import Document

        doc = Document(
            id=doc_id,
            project_id=project_id,
            doc_type="tender_file",
            title="t.pdf",
            storage_key="k",
            status="parsing",
        )
        db = MagicMock()
        db.flush = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = doc
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        glossary = [{"term": "AI", "canonical": "人工智能", "desc": ""}]
        parsed = ParsedTender(
            score_points=[{"clause_no": "1", "item": "方案"}],
            tech_requirements=[],
            glossary=glossary,
        )
        await parse_service.save_parse_result(db, project_id, doc_id, parsed)
        assert doc.meta.get("glossary") == glossary


class TestUnifyTerms:
    def test_replace_term_with_canonical(self) -> None:
        text = "本方案采用AI技术，AI能力覆盖全场景。"
        glossary = [{"term": "AI", "canonical": "人工智能"}]
        assert glossary_service.unify_terms(text, glossary) == (
            "本方案采用人工智能技术，人工智能能力覆盖全场景。"
        )

    def test_empty_glossary_passthrough(self) -> None:
        assert glossary_service.unify_terms("任意正文", []) == "任意正文"

    def test_skip_placeholder_terms(self) -> None:
        """mock 占位术语（term == 'mock' 或空）不参与替换."""
        glossary = [{"term": "mock", "canonical": "mock"}, {"term": "", "canonical": "X"}]
        assert glossary_service.unify_terms("mock 正文", glossary) == "mock 正文"


class TestIntegrateNodeGlossary:
    @pytest.mark.asyncio
    async def test_mock_mode_passthrough(self) -> None:
        """mock 模式 integrate 不做术语替换（确定性输出）."""
        from app.agents import nodes

        chapters = {"1": "本方案采用AI技术。"}
        state = {
            "project_id": str(uuid.uuid4()),
            "outline": [{"chapter_no": "1", "title": "T"}],
            "chapters": chapters,
            "glossary": [{"term": "AI", "canonical": "人工智能"}],
        }
        from tests.agents.test_nodes import FakeDB

        with (
            patch.object(nodes, "async_session_factory", lambda: FakeDB()),
            patch.object(nodes, "publish_event", AsyncMock()),
            patch.object(nodes.settings_service, "is_mock_enabled", AsyncMock(return_value=True)),
        ):
            result = await nodes.integrate_node(state)
        assert result["chapters"]["1"] == "本方案采用AI技术。"
        assert result["current_phase"] == "review"

    @pytest.mark.asyncio
    async def test_real_mode_unifies_terms(self) -> None:
        """真实模式 integrate 按术语表统一术语并落库."""
        from app.agents import nodes

        chapters = {"1": "本方案采用AI技术。"}
        state = {
            "project_id": str(uuid.uuid4()),
            "outline": [{"chapter_no": "1", "title": "T"}],
            "chapters": chapters,
            "glossary": [{"term": "AI", "canonical": "人工智能"}],
        }
        from tests.agents.test_nodes import FakeDB

        with (
            patch.object(nodes, "async_session_factory", lambda: FakeDB()),
            patch.object(nodes, "publish_event", AsyncMock()),
            patch.object(nodes.settings_service, "is_mock_enabled", AsyncMock(return_value=False)),
        ):
            result = await nodes.integrate_node(state)
        assert result["chapters"]["1"] == "本方案采用人工智能技术。"
