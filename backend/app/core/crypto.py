"""对称加密工具 — LLM 页面配置密钥落库加密（Fernet）.

Fernet key 优先由 settings.llm_crypto_secret（env BID_LLM_CRYPTO_SECRET）经
sha256 摘要 → urlsafe_b64 派生（W-2：与 JWT 签名密钥隔离）；未配置时回退
settings.jwt_secret 派生并告警一次。生产环境务必同时设置高强度
BID_LLM_CRYPTO_SECRET 与 BID_JWT_SECRET。
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.core.config import settings

logger = logging.getLogger(__name__)

_fallback_warned = False  # 回退告警只打一次（避免高频加密路径刷屏）


def derive_fernet_key(secret: str) -> bytes:
    """由任意 secret 派生 32 字节 Fernet key（sha256 → urlsafe_b64，确定性）."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    global _fallback_warned
    secret = settings.llm_crypto_secret
    if not secret:
        if not _fallback_warned:
            logger.warning(
                "BID_LLM_CRYPTO_SECRET 未配置，LLM 密钥加密回退使用 jwt_secret 派生，"
                "建议配置独立加密密钥（W-2）"
            )
            _fallback_warned = True
        secret = settings.jwt_secret
    return Fernet(derive_fernet_key(secret))


def encrypt_secret(plaintext: str) -> str:
    """加密明文密钥，返回 Fernet token 字符串."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """解密 Fernet token，非法密文抛 cryptography.fernet.InvalidToken（由调用方捕获回退）."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
