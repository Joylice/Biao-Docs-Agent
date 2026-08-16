"""core/crypto 测试 — Fernet key 派生 + 加解密往返 + 独立加密密钥（W-2，纯函数，无需 DB）."""

import logging

import pytest
from cryptography.fernet import InvalidToken

from app.core import crypto as crypto_module
from app.core.config import settings
from app.core.crypto import decrypt_secret, derive_fernet_key, encrypt_secret


class TestDeriveFernetKey:
    """jwt_secret → Fernet key 派生."""

    def test_deterministic(self) -> None:
        """相同 secret 派生出相同 key."""
        assert derive_fernet_key("some-secret") == derive_fernet_key("some-secret")

    def test_different_secret_different_key(self) -> None:
        """不同 secret 派生出不同 key."""
        assert derive_fernet_key("secret-a") != derive_fernet_key("secret-b")

    def test_key_is_urlsafe_b64_44_chars(self) -> None:
        """Fernet key 为 44 字符 urlsafe base64（32 字节 sha256 摘要）."""
        key = derive_fernet_key("any-secret")
        assert isinstance(key, bytes)
        assert len(key) == 44


class TestEncryptDecrypt:
    """加解密往返与安全性."""

    @pytest.mark.parametrize(
        "plain",
        ["sk-abc123XYZ", "中文密钥", "a", "sk-" + "x" * 200],
    )
    def test_roundtrip(self, plain: str) -> None:
        """加密后解密还原原文."""
        assert decrypt_secret(encrypt_secret(plain)) == plain

    def test_ciphertext_does_not_leak_plaintext(self) -> None:
        """密文中不含明文."""
        token = encrypt_secret("sk-super-secret-key")
        assert "sk-super-secret-key" not in token

    def test_decrypt_invalid_token_raises(self) -> None:
        """解密非法密文抛 InvalidToken（由上层捕获回退）."""
        with pytest.raises(InvalidToken):
            decrypt_secret("not-a-valid-fernet-token")


class TestIndependentCryptoSecret:
    """W-2：优先 BID_LLM_CRYPTO_SECRET 派生；为空回退 jwt_secret 并 warning 一次."""

    def test_independent_secret_used_when_configured(self, monkeypatch) -> None:
        """配置独立密钥 → 派生源与 jwt_secret 不同（切回后旧密文解密失败）."""
        monkeypatch.setattr(settings, "llm_crypto_secret", "independent-secret-1")
        token = encrypt_secret("sk-x")

        # 切回 jwt_secret 派生：密钥不同 → 解密应失败，证明独立密钥实际生效
        monkeypatch.setattr(settings, "llm_crypto_secret", "")
        monkeypatch.setattr(crypto_module, "_fallback_warned", False)
        with pytest.raises(InvalidToken):
            decrypt_secret(token)

    def test_independent_secret_roundtrip(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_crypto_secret", "independent-secret-2")
        assert decrypt_secret(encrypt_secret("sk-y")) == "sk-y"

    def test_fallback_to_jwt_secret_warns_once(self, monkeypatch, caplog) -> None:
        """独立密钥为空 → 回退 jwt_secret 派生，warning 仅一次且加解密仍可用."""
        monkeypatch.setattr(settings, "llm_crypto_secret", "")
        monkeypatch.setattr(crypto_module, "_fallback_warned", False)

        with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
            token = encrypt_secret("sk-z")
            encrypt_secret("sk-w")

        fallback_records = [r for r in caplog.records if "BID_LLM_CRYPTO_SECRET" in r.getMessage()]
        assert len(fallback_records) == 1
        assert decrypt_secret(token) == "sk-z"
