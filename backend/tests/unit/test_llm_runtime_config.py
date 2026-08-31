"""llm_service / rag_service 运行时配置测试 — 库内密钥优先于 env（litellm 全 mock）."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services.infra import settings_service
from app.services.infra.settings_service import RuntimeLlmConfig
from app.services.llm import llm_service, rag_service
from app.services.llm.llm_service import call_llm_text, call_llm_with_schema
from app.services.llm.rag_service import get_embedding


@pytest.fixture
def fake_litellm(monkeypatch):
    """注入假 litellm 模块（铁律：禁止真实调用 LLM）."""
    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def _patch_cfg(monkeypatch, cfg: RuntimeLlmConfig | None) -> None:
    async def fake_get_runtime_config():
        return cfg

    monkeypatch.setattr(settings_service, "get_runtime_config", fake_get_runtime_config)


@pytest.fixture(autouse=True)
def _no_env_mock(monkeypatch):
    """默认关闭 env mock，聚焦库内配置行为."""
    monkeypatch.setattr(settings, "llm_mock", False)


class TestLlmServiceDbKeyPriority:
    """acompletion 的 api_key：库内配置优先，无则不传（回退 env）."""

    async def test_deepseek_model_uses_db_deepseek_key(self, fake_litellm, monkeypatch) -> None:
        _patch_cfg(monkeypatch, RuntimeLlmConfig(deepseek_api_key="sk-db-deepseek"))
        monkeypatch.setattr(settings, "llm_model", "deepseek/deepseek-chat")
        fake_litellm.acompletion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
            )
        )

        await call_llm_text("s", "u", mock=False)

        kwargs = fake_litellm.acompletion.call_args.kwargs
        assert kwargs["api_key"] == "sk-db-deepseek"

    async def test_qwen_model_uses_db_dashscope_key(self, fake_litellm, monkeypatch) -> None:
        _patch_cfg(monkeypatch, RuntimeLlmConfig(dashscope_api_key="sk-db-dashscope"))
        monkeypatch.setattr(settings, "llm_model", "qwen/qwen-plus")
        fake_litellm.acompletion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
            )
        )

        await call_llm_text("s", "u", mock=False)

        kwargs = fake_litellm.acompletion.call_args.kwargs
        assert kwargs["api_key"] == "sk-db-dashscope"

    async def test_no_db_config_falls_back_to_env(self, fake_litellm, monkeypatch) -> None:
        """库内无配置：不传 api_key，litellm 自行读环境变量（现状回退）."""
        _patch_cfg(monkeypatch, None)
        fake_litellm.acompletion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 1}'))]
            )
        )

        await call_llm_with_schema("s", "u", response_format=None, mock=False)

        kwargs = fake_litellm.acompletion.call_args.kwargs
        assert "api_key" not in kwargs

    async def test_db_llm_mock_enables_mock(self, fake_litellm, monkeypatch) -> None:
        """库内 llm_mock=true（env=false）→ 走 mock 分支，不调 litellm."""
        _patch_cfg(monkeypatch, RuntimeLlmConfig(llm_mock=True, deepseek_api_key="sk-x"))

        text = await call_llm_text("s", "u")

        fake_litellm.acompletion.assert_not_called()
        assert text.strip()


class TestEmbeddingDbConfigPriority:
    """aembedding 的 api_base：库内配置优先于 env."""

    async def test_db_api_base_overrides_env(self, fake_litellm, monkeypatch) -> None:
        _patch_cfg(monkeypatch, RuntimeLlmConfig(embedding_api_base="http://db-emb:11434/v1"))
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2]}])
        )

        await get_embedding("真实路径", mock=False)

        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert kwargs["api_base"] == "http://db-emb:11434/v1"

    async def test_no_db_config_falls_back_to_env_base(self, fake_litellm, monkeypatch) -> None:
        _patch_cfg(monkeypatch, None)
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2]}])
        )

        await get_embedding("真实路径", mock=False)

        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert kwargs["api_base"] == settings.embedding_api_base

    async def test_dashscope_model_uses_db_dashscope_key(self, fake_litellm, monkeypatch) -> None:
        """dashscope 前缀模型（云端 embedding）→ aembedding 收到库内 dashscope key."""
        _patch_cfg(monkeypatch, RuntimeLlmConfig(dashscope_api_key="sk-db-dashscope"))
        monkeypatch.setattr(settings, "embedding_model", "dashscope/text-embedding-v3")
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2]}])
        )

        await get_embedding("真实路径", mock=False)

        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert kwargs["api_key"] == "sk-db-dashscope"

    async def test_batch_uses_db_dashscope_key(self, fake_litellm, monkeypatch) -> None:
        """批量路径同样传 api_key."""
        _patch_cfg(monkeypatch, RuntimeLlmConfig(dashscope_api_key="sk-db-dashscope"))
        monkeypatch.setattr(settings, "embedding_model", "dashscope/text-embedding-v3")
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(
                data=[{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]
            )
        )

        await rag_service.get_embeddings_batch(["a", "b"], mock=False)

        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert kwargs["api_key"] == "sk-db-dashscope"

    async def test_no_db_config_does_not_pass_api_key(self, fake_litellm, monkeypatch) -> None:
        """库内无配置：不传 api_key（litellm 回退 env，保持现状容错）."""
        _patch_cfg(monkeypatch, None)
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2]}])
        )

        await get_embedding("真实路径", mock=False)

        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert "api_key" not in kwargs

    async def test_db_llm_mock_enables_embedding_mock(self, fake_litellm, monkeypatch) -> None:
        """库内 llm_mock=true → embedding 同样走 mock."""
        _patch_cfg(monkeypatch, RuntimeLlmConfig(llm_mock=True))

        vec = await get_embedding("离线")

        fake_litellm.aembedding.assert_not_called()
        assert vec.shape == (settings.embedding_dimension,)


class TestLlmServiceModuleSurface:
    """防止回归：llm_service 不再持有同步 _is_mock_mode（mock 判定下沉 settings_service）."""

    def test_no_sync_mock_helper(self) -> None:
        assert not hasattr(llm_service, "_is_mock_mode")
        assert not hasattr(rag_service, "_is_mock_mode")
