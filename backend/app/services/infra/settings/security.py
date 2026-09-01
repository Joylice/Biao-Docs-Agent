"""LLM 配置安全工具 — 密钥脱敏、SSRF 防护、密文解密（纯函数，无共享状态）.

从原 settings_service 拆分（第一轮模块拆分）：本模块只包含无副作用的安全工具，
被 runtime/storage 子模块与外部测试直接引用。
"""

import ipaddress
import logging
import re
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# S-1：疑似脱敏串（前缀仅含密钥常见字符 + 连续 4 星号），服务端拒收避免把掩码存库
_MASKED_KEY_RE = re.compile(r"^[A-Za-z0-9_-]*\*{4}.*")

# SSRF 防护：localhost 域名别名（IP 字面量由 ipaddress 判定）
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def mask_secret(plain: str) -> str:
    """密钥脱敏展示：sk-****<后4位>；空串原样返回."""
    if not plain:
        return ""
    return f"sk-****{plain[-4:]}"


def _validate_api_base(url: str, field: str) -> None:
    """SSRF 防护公共实现：校验 http(s) 地址不得指向内网/本机目标.

    规则（两档）：
    - 仅允许 http/https scheme；
    - host 为 IP 字面量时拒绝私网段（10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、
      127.0.0.0/8、169.254.0.0/16、::1、0.0.0.0 等，以 ipaddress 分类判定）；
      settings.debug=True 时仅放行 loopback（本地 Ollama 开发场景）；
    - host 为域名时不做 DNS 解析，仅拒绝 localhost 别名（非 debug）。

    残余风险：域名类 host 可能在解析阶段被指向内网（DNS rebinding），本层不解析
    DNS；生产部署建议同时以网络层策略限制出站。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError(f"{field} 必须为合法的 http/https 地址")

    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        lowered = host.lower()
        is_local = lowered in _LOCAL_HOSTNAMES or lowered.endswith(".localhost")
        if is_local and not settings.debug:
            raise ValidationError(f"{field} 不允许指向 localhost（本机目标）") from None
        return  # 普通域名：放行（DNS rebinding 残余风险见 docstring）

    if settings.debug and ip.is_loopback:
        return  # debug 档放行本机回环（本地 Ollama 默认 http://localhost:11434/v1）
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_multicast
    ):
        raise ValidationError(f"{field} 不允许指向内网/本机地址")


def validate_embedding_api_base(url: str) -> None:
    """SSRF 防护：校验 embedding_api_base 不得指向内网/本机目标."""
    _validate_api_base(url, "embedding_api_base")


def validate_llm_api_base(url: str) -> None:
    """SSRF 防护：校验 llm_api_base 不得指向内网/本机目标."""
    _validate_api_base(url, "llm_api_base")


def _decrypt_or_empty(token: str | None) -> str:
    """解密失败/空值 → 空串（脏数据不阻断读取）."""
    if not token:
        return ""
    try:
        return decrypt_secret(token)
    except InvalidToken:
        logger.warning("llm_settings 密文解密失败，按未配置处理")
        return ""


def _reject_masked_key(field: str, value: str) -> None:
    """S-1：拒收疑似脱敏串（如 GET 回显的 sk-****1234 被误存回库）."""
    if _MASKED_KEY_RE.match(value):
        raise ValidationError(f"{field} 疑似脱敏串，请填写真实密钥")
