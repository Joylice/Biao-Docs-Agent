"""Reranker 精排服务测试（云端 API，DashScope gte-rerank 兼容协议）.

安全与降级约定：
- mock 模式 / 未启用 / 未配置 api_key → 原序直通（不外发）；
- 外发前候选文本必须经 redact 脱敏；
- API 异常或返回结构非法 → 降级返回原向量序，不阻塞检索链路。
"""

import uuid
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import rerank_service
from app.services.rag_service import ChunkResult


def _chunk(content: str, score: float = 0.5) -> ChunkResult:
    return ChunkResult(
        chunk_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        content=content,
        page_no=1,
        score=score,
    )


def _api_result(pairs: list[tuple[int, float]]) -> dict:
    """构造 DashScope rerank 响应：results=[{index, relevance_score}]."""
    return {
        "output": {"results": [{"index": idx, "relevance_score": score} for idx, score in pairs]}
    }


async def _fake_not_mock(_mock=None) -> bool:
    return False


async def _fake_mock(_mock=None) -> bool:
    return True


@pytest.fixture(autouse=True)
def _rerank_env(monkeypatch):
    """默认开启 rerank 并配置密钥（用例内可覆盖）."""
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "rerank_api_base", "https://rerank.example.com/api/v1")
    monkeypatch.setattr(settings, "rerank_api_key", "sk-test-key")
    monkeypatch.setattr(settings, "rerank_model", "gte-rerank")


class TestRerankPassThrough:
    """直通场景：不调用远程 API，原序返回."""

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self, monkeypatch) -> None:
        """空候选直通空列表."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        result = await rerank_service.rerank("查询", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_mock_mode_pass_through(self, monkeypatch) -> None:
        """LLM mock 模式下 rerank 直通原序（确定性，便于测试）."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_mock)
        chunks = [_chunk("a"), _chunk("b")]
        with patch.object(rerank_service, "_post_rerank") as post:
            result = await rerank_service.rerank("查询", chunks)
        assert result == chunks
        post.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_pass_through(self, monkeypatch) -> None:
        """rerank_enabled=False 直通."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        monkeypatch.setattr(settings, "rerank_enabled", False)
        chunks = [_chunk("a"), _chunk("b")]
        with patch.object(rerank_service, "_post_rerank") as post:
            result = await rerank_service.rerank("查询", chunks)
        assert result == chunks
        post.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_api_key_pass_through(self, monkeypatch) -> None:
        """未配置 api_key 直通（避免无凭据请求）."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        monkeypatch.setattr(settings, "rerank_api_key", "")
        chunks = [_chunk("a")]
        with patch.object(rerank_service, "_post_rerank") as post:
            result = await rerank_service.rerank("查询", chunks)
        assert result == chunks
        post.assert_not_called()


class TestRerankReorder:
    """正常重排：按 relevance_score 降序重排候选."""

    @pytest.mark.asyncio
    async def test_reorders_by_relevance(self, monkeypatch) -> None:
        """远程返回乱序 index → 候选按相关度重排."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        c0, c1, c2 = _chunk("c0"), _chunk("c1"), _chunk("c2")
        # index 2 最相关、0 次之、1 最低
        payload = _api_result([(2, 0.95), (0, 0.6), (1, 0.1)])
        with patch.object(rerank_service, "_post_rerank", return_value=payload) as post:
            result = await rerank_service.rerank("查询", [c0, c1, c2])
        assert [c.content for c in result] == ["c2", "c0", "c1"]
        post.assert_called_once()

    @pytest.mark.asyncio
    async def test_payload_redacts_content(self, monkeypatch) -> None:
        """外发 body 中的候选文本必须脱敏（手机号被遮蔽）."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        chunks = [_chunk("联系电话 13812345678 请联系")]
        captured: dict = {}

        def fake_post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
            captured["payload"] = payload
            return _api_result([(0, 0.9)])

        with patch.object(rerank_service, "_post_rerank", side_effect=fake_post):
            await rerank_service.rerank("查询", chunks)
        sent = captured["payload"]["input"]["documents"][0]
        assert "13812345678" not in sent

    @pytest.mark.asyncio
    async def test_request_headers_carry_key_and_model(self, monkeypatch) -> None:
        """Authorization 与 model 随请求下发（密钥不入日志由实现保证）."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        captured: dict = {}

        def fake_post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
            captured["headers"] = headers
            captured["payload"] = payload
            captured["url"] = url
            return _api_result([(0, 0.9)])

        with patch.object(rerank_service, "_post_rerank", side_effect=fake_post):
            await rerank_service.rerank("查询", [_chunk("a")])
        assert captured["headers"]["Authorization"] == "Bearer sk-test-key"
        assert captured["payload"]["model"] == "gte-rerank"
        assert captured["url"] == "https://rerank.example.com/api/v1"


class TestRerankDegrade:
    """降级场景：API 失败/非法返回 → 原序返回，不抛异常."""

    @pytest.mark.asyncio
    async def test_api_exception_degrades_to_original_order(self, monkeypatch) -> None:
        """HTTP 异常 → 原向量序."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        chunks = [_chunk("a"), _chunk("b")]
        with patch.object(rerank_service, "_post_rerank", side_effect=ConnectionError("boom")):
            result = await rerank_service.rerank("查询", chunks)
        assert result == chunks

    @pytest.mark.asyncio
    async def test_malformed_response_degrades(self, monkeypatch) -> None:
        """响应结构非法（缺 output.results）→ 原序."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        chunks = [_chunk("a"), _chunk("b")]
        with patch.object(rerank_service, "_post_rerank", return_value={"foo": 1}):
            result = await rerank_service.rerank("查询", chunks)
        assert result == chunks

    @pytest.mark.asyncio
    async def test_out_of_range_index_ignored(self, monkeypatch) -> None:
        """越界 index 被忽略，其余按分排序；未命中的候选按原序补尾."""
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)
        c0, c1, c2 = _chunk("c0"), _chunk("c1"), _chunk("c2")
        payload = _api_result([(9, 0.99), (2, 0.8), (0, 0.5)])
        with patch.object(rerank_service, "_post_rerank", return_value=payload):
            result = await rerank_service.rerank("查询", [c0, c1, c2])
        assert [c.content for c in result] == ["c2", "c0", "c1"]
