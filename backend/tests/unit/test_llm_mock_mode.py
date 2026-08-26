"""BID_LLM_MOCK 模式测试 — llm_service / rag_service 的 mock 开关生效."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.core.config import settings
from app.services.llm.llm_service import _MOCK_TEXT, call_llm_text, call_llm_with_schema
from app.services.llm.rag_service import get_embedding, get_embeddings_batch

PARSE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "tender_parse_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "tender_no": {"type": "string"},
                "score_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "clause_no": {"type": "string"},
                            "item": {"type": "string"},
                            "score": {"type": "number"},
                            "criteria": {"type": "string"},
                            "is_star": {"type": "boolean"},
                            "risk_level": {"type": "string"},
                        },
                        "required": ["clause_no", "item"],
                    },
                },
                "tech_requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "seq": {"type": "integer"},
                            "description": {"type": "string"},
                            "category": {"type": "string"},
                            "is_mandatory": {"type": "boolean"},
                        },
                        "required": ["seq", "description"],
                    },
                },
            },
            "required": ["score_points", "tech_requirements"],
        },
    },
}

OUTLINE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "outline",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "chapters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chapter_no": {"type": "string"},
                            "title": {"type": "string"},
                            "sections": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["chapter_no", "title"],
                    },
                }
            },
            "required": ["chapters"],
        },
    },
}

REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "review_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chapter_no": {"type": "string"},
                            "comment": {"type": "string"},
                            "action": {"type": "string"},
                            "severity": {"type": "string"},
                        },
                        "required": ["chapter_no", "comment", "action"],
                    },
                }
            },
            "required": ["comments"],
        },
    },
}


@pytest.fixture
def fake_litellm(monkeypatch):
    """注入假 litellm 模块，用于断言未发生真实调用."""
    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


class TestCallLlmMockMode:
    """call_llm_with_schema / call_llm_text 的 mock 模式."""

    async def test_schema_mock_via_param(self, fake_litellm) -> None:
        """mock=True 时返回符合 schema 的数据且不调用 litellm."""
        result = await call_llm_with_schema(
            system_prompt="s",
            user_prompt="u",
            response_format=PARSE_RESPONSE_FORMAT,
            mock=True,
        )
        fake_litellm.acompletion.assert_not_called()

        assert isinstance(result["score_points"], list) and result["score_points"]
        sp = result["score_points"][0]
        assert "clause_no" in sp and "item" in sp

        assert isinstance(result["tech_requirements"], list) and result["tech_requirements"]
        tr = result["tech_requirements"][0]
        assert "seq" in tr and "description" in tr

    async def test_schema_mock_via_settings(self, fake_litellm, monkeypatch) -> None:
        """settings.llm_mock=True 时同样走 mock（等价 BID_LLM_MOCK=true）."""
        monkeypatch.setattr(settings, "llm_mock", True)
        result = await call_llm_with_schema(
            system_prompt="s",
            user_prompt="u",
            response_format=OUTLINE_RESPONSE_FORMAT,
        )
        fake_litellm.acompletion.assert_not_called()

        chapters = result.get("chapters", [])
        assert chapters, "mock 大纲章节不能为空（下游要求非空）"
        assert "chapter_no" in chapters[0] and "title" in chapters[0]
        assert isinstance(chapters[0]["sections"], list) and chapters[0]["sections"]

    async def test_schema_mock_review_structure(self, fake_litellm) -> None:
        """review 结构的 mock 数据包含 comments 列表."""
        result = await call_llm_with_schema(
            system_prompt="s",
            user_prompt="u",
            response_format=REVIEW_RESPONSE_FORMAT,
            mock=True,
        )
        fake_litellm.acompletion.assert_not_called()
        comments = result.get("comments")
        assert isinstance(comments, list)
        assert all({"chapter_no", "comment", "action"} <= set(c.keys()) for c in comments)

    async def test_schema_mock_stable(self) -> None:
        """mock 数据稳定：相同入参多次调用结果一致."""
        r1 = await call_llm_with_schema("s", "u", response_format=PARSE_RESPONSE_FORMAT, mock=True)
        r2 = await call_llm_with_schema("s", "u", response_format=PARSE_RESPONSE_FORMAT, mock=True)
        assert r1 == r2

    async def test_text_mock_via_param(self, fake_litellm) -> None:
        """call_llm_text mock=True 返回非空字符串且不调用 litellm."""
        text = await call_llm_text("s", "u", mock=True)
        fake_litellm.acompletion.assert_not_called()
        assert isinstance(text, str) and text.strip()

    async def test_text_mock_via_settings(self, fake_litellm, monkeypatch) -> None:
        """settings.llm_mock=True 时 call_llm_text 走 mock."""
        monkeypatch.setattr(settings, "llm_mock", True)
        text = await call_llm_text("s", "u")
        fake_litellm.acompletion.assert_not_called()
        assert text.strip()

    async def test_text_mock_length_meets_min_chapter(self) -> None:
        """mock 文本长度须 ≥ nodes.MIN_CHAPTER_LENGTH=200，避免章节字数校验重试."""
        assert len(_MOCK_TEXT) >= 200

    async def test_param_false_overrides_settings(self, fake_litellm, monkeypatch) -> None:
        """mock=False 显式覆盖 settings.llm_mock=True，仍走真实调用路径."""
        monkeypatch.setattr(settings, "llm_mock", True)
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 1}'))]
        )
        fake_litellm.acompletion = AsyncMock(return_value=resp)

        result = await call_llm_with_schema("s", "u", mock=False)
        fake_litellm.acompletion.assert_awaited_once()
        assert result == {"ok": 1}


class TestEmbeddingMockMode:
    """get_embedding / get_embeddings_batch 的 mock 模式."""

    async def test_embedding_mock_deterministic(self, fake_litellm) -> None:
        """相同文本返回相同向量，维度 = settings.embedding_dimension."""
        v1 = await get_embedding("测试文本 A", mock=True)
        v2 = await get_embedding("测试文本 A", mock=True)
        fake_litellm.aembedding.assert_not_called()

        assert v1.shape == (settings.embedding_dimension,)
        np.testing.assert_array_equal(v1, v2)

    async def test_embedding_mock_different_text(self) -> None:
        """不同文本产生不同向量."""
        v1 = await get_embedding("文本甲", mock=True)
        v2 = await get_embedding("文本乙", mock=True)
        assert not np.array_equal(v1, v2)

    async def test_embedding_mock_via_settings(self, fake_litellm, monkeypatch) -> None:
        """settings.llm_mock=True 时 embedding 也走 mock."""
        monkeypatch.setattr(settings, "llm_mock", True)
        vec = await get_embedding("离线测试")
        fake_litellm.aembedding.assert_not_called()
        assert vec.shape == (settings.embedding_dimension,)

    async def test_embeddings_batch_mock(self, fake_litellm) -> None:
        """批量 mock 向量与单条结果一致."""
        texts = ["块一", "块二", "块三"]
        batch = await get_embeddings_batch(texts, mock=True)
        fake_litellm.aembedding.assert_not_called()

        assert batch.shape == (len(texts), settings.embedding_dimension)
        for i, t in enumerate(texts):
            single = await get_embedding(t, mock=True)
            np.testing.assert_array_equal(batch[i], single)

    async def test_embedding_mock_param_false_calls_litellm(
        self, fake_litellm, monkeypatch
    ) -> None:
        """mock=False 显式覆盖 settings，仍调用 litellm aembedding."""
        monkeypatch.setattr(settings, "llm_mock", True)
        dim = settings.embedding_dimension
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1] * dim}])
        )
        vec = await get_embedding("真实路径", mock=False)
        fake_litellm.aembedding.assert_awaited_once()
        assert vec.shape == (dim,)
