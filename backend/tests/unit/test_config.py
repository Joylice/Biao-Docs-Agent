"""应用配置测试 — 关键默认值契约."""

from app.core.config import Settings


def test_embedding_model_default_has_provider_prefix(monkeypatch) -> None:
    """未设置 BID_EMBEDDING_MODEL 时默认带 litellm provider 前缀（DashScope 云端）."""
    monkeypatch.delenv("BID_EMBEDDING_MODEL", raising=False)
    assert Settings().embedding_model == "dashscope/text-embedding-v3"


def test_embedding_model_overridable_by_env(monkeypatch) -> None:
    """BID_EMBEDDING_MODEL 可覆盖默认值（如本地 Ollama 的 bge-m3）."""
    monkeypatch.setenv("BID_EMBEDDING_MODEL", "ollama/bge-m3")
    assert Settings().embedding_model == "ollama/bge-m3"
