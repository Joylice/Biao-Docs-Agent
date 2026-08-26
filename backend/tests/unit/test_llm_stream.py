"""llm_service.call_llm_stream 测试 — 三期 S4 真流式（mock 切片 / 真实 stream）."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.llm.llm_service import _MOCK_TEXT, call_llm_stream


def _chunk(content: str | None) -> SimpleNamespace:
    """构造 LiteLLM 流式 chunk（choices[0].delta.content）."""
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class TestStreamMockMode:
    """mock 模式：_MOCK_TEXT 按 ~20 字切片 yield."""

    @pytest.mark.asyncio
    async def test_slices_reassemble_to_mock_text(self) -> None:
        """切片拼接 == _MOCK_TEXT（完整性）."""
        chunks = [c async for c in call_llm_stream("s", "u", mock=True)]
        assert len(chunks) > 1, "mock 应分多片流式输出"
        assert "".join(chunks) == _MOCK_TEXT

    @pytest.mark.asyncio
    async def test_slice_size_bounded(self) -> None:
        """单片 ≤ 20 字符."""
        chunks = [c async for c in call_llm_stream("s", "u", mock=True)]
        assert all(len(c) <= 20 for c in chunks)


class TestStreamRealMode:
    """真实模式：acompletion(stream=True)，逐 chunk yield delta（跳过空 delta）."""

    @pytest.mark.asyncio
    async def test_yields_deltas_and_skips_empty(self, monkeypatch) -> None:
        captured: dict = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)

            async def gen():
                yield _chunk("你好")
                yield _chunk(None)  # 空 delta：跳过
                yield _chunk("")  # 空串 delta：跳过
                yield _chunk("，世界")

            return gen()

        mock_litellm = MagicMock()
        mock_litellm.acompletion = fake_acompletion
        monkeypatch.setitem(sys.modules, "litellm", mock_litellm)
        monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _false)

        async def no_runtime_config():
            return None

        monkeypatch.setattr(
            "app.services.infra.settings_service.get_runtime_config", no_runtime_config
        )

        chunks = [c async for c in call_llm_stream("s", "u", mock=False)]
        assert chunks == ["你好", "，世界"]
        assert captured["stream"] is True
        assert captured["temperature"] == 0.7


async def _false(mock: bool | None = None) -> bool:
    return False
