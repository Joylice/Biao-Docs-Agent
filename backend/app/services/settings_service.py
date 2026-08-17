"""LLM 配置服务 — 页面配置读写（加密/脱敏）、运行时解析、连通性测试.

运行时生效策略（选型说明）：
- ``get_runtime_config()`` 带 **30s TTL 进程内缓存**。理由：llm_service/rag_service
  被 LangGraph 节点与 worker 高频调用且无 db 会话可传，逐次查库会带来连接开销；
  30s 缓存把页面改动的传播延迟控制在可接受范围。
- 缓存失效由 **api 层在 commit 成功之后** 调用 ``invalidate_runtime_cache()``
  （W-1：避免事务未提交即失效导致读到旧值）；跨进程（arq worker）靠 TTL 过期
  收敛（≤30s）。
- DB 不可达/无表：捕获异常回退 None（调用方退回环境变量现状），并做 5s 负缓存
  避免反复重连。
"""

import asyncio
import ipaddress
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import async_session_factory
from app.core.exceptions import ValidationError
from app.models.llm_settings import LlmSetting
from app.schemas.settings import LlmSettingsUpdate

logger = logging.getLogger(__name__)

# 运行时配置缓存：(monotonic 时间戳, 配置；None 表示无行/DB 失败)
_runtime_cache: tuple[float, "RuntimeLlmConfig | None"] | None = None
RUNTIME_CACHE_TTL = 30.0  # 秒：正常缓存有效期
FAILURE_CACHE_TTL = 5.0  # 秒：无行/DB 失败的负缓存（避免频繁查库/重连）

TEST_TIMEOUT_SECONDS = 15.0  # 连通性测试超时上限
_NOT_CONFIGURED_ERROR = "未配置密钥或处于 mock 模式"

# S-1：疑似脱敏串（前缀仅含密钥常见字符 + 连续 4 星号），服务端拒收避免把掩码存库
_MASKED_KEY_RE = re.compile(r"^[A-Za-z0-9_-]*\*{4}.*")

# SSRF 防护：localhost 域名别名（IP 字面量由 ipaddress 判定）
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


@dataclass
class RuntimeLlmConfig:
    """llm_settings 解密后的运行时视图."""

    deepseek_api_key: str | None = None
    dashscope_api_key: str | None = None
    embedding_api_base: str | None = None
    llm_mock: bool = False

    def api_key_for(self, model: str) -> str | None:
        """按模型前缀匹配库内密钥：deepseek → DeepSeek key，qwen/dashscope → DashScope key."""
        if model.startswith("deepseek"):
            return self.deepseek_api_key
        if model.startswith("qwen") or model.startswith("dashscope"):
            return self.dashscope_api_key
        return None


def mask_secret(plain: str) -> str:
    """密钥脱敏展示：sk-****<后4位>；空串原样返回."""
    if not plain:
        return ""
    return f"sk-****{plain[-4:]}"


def invalidate_runtime_cache() -> None:
    """清空运行时配置缓存（api 层 commit 成功后调用，本进程即时生效）."""
    global _runtime_cache
    _runtime_cache = None


def validate_embedding_api_base(url: str) -> None:
    """SSRF 防护：校验 embedding_api_base 不得指向内网/本机目标.

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
        raise ValidationError("embedding_api_base 必须为合法的 http/https 地址")

    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        lowered = host.lower()
        is_local = lowered in _LOCAL_HOSTNAMES or lowered.endswith(".localhost")
        if is_local and not settings.debug:
            raise ValidationError("embedding_api_base 不允许指向 localhost（本机目标）") from None
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
        raise ValidationError("embedding_api_base 不允许指向内网/本机地址")


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


# ── 读写（api 层入口）──


async def get_llm_settings(db: AsyncSession) -> LlmSetting | None:
    """读取单行配置（只读，不 commit）."""
    result = await db.execute(select(LlmSetting).limit(1))
    return result.scalar_one_or_none()


async def get_settings_view(db: AsyncSession) -> dict[str, Any]:
    """GET 视图：密钥脱敏 + configured 标志；未配置的 base/mock 展示 env 生效值."""
    row = await get_llm_settings(db)
    if row is None:
        return {
            "deepseek_api_key": "",
            "dashscope_api_key": "",
            "embedding_api_base": settings.embedding_api_base,
            "llm_mock": settings.llm_mock,
            "deepseek_configured": False,
            "dashscope_configured": False,
        }
    deepseek = _decrypt_or_empty(row.deepseek_api_key_enc)
    dashscope = _decrypt_or_empty(row.dashscope_api_key_enc)
    return {
        "deepseek_api_key": mask_secret(deepseek),
        "dashscope_api_key": mask_secret(dashscope),
        "embedding_api_base": row.embedding_api_base or settings.embedding_api_base,
        "llm_mock": row.llm_mock,
        "deepseek_configured": bool(deepseek),
        "dashscope_configured": bool(dashscope),
    }


async def update_llm_settings(db: AsyncSession, payload: LlmSettingsUpdate) -> list[str]:
    """upsert 更新。密钥字段三态（W-5）：None=保持不变、""=清除、非空=更新；
    embedding_api_base/llm_mock 必填全量。密钥加密入库，疑似脱敏串拒收（S-1），
    非空 base 做 SSRF 校验。返回变更字段名清单（供审计）。

    注意（W-1）：本函数不做缓存失效，由 api 层在 commit 成功后调用
    ``invalidate_runtime_cache()``。
    """
    row = await get_llm_settings(db)
    if row is None:
        row = LlmSetting()
        db.add(row)

    changed: list[str] = []

    if payload.deepseek_api_key is not None:
        new_deepseek = payload.deepseek_api_key.strip()
        _reject_masked_key("deepseek_api_key", new_deepseek)
        if new_deepseek != _decrypt_or_empty(row.deepseek_api_key_enc):
            changed.append("deepseek_api_key")
        row.deepseek_api_key_enc = encrypt_secret(new_deepseek) if new_deepseek else None

    if payload.dashscope_api_key is not None:
        new_dashscope = payload.dashscope_api_key.strip()
        _reject_masked_key("dashscope_api_key", new_dashscope)
        if new_dashscope != _decrypt_or_empty(row.dashscope_api_key_enc):
            changed.append("dashscope_api_key")
        row.dashscope_api_key_enc = encrypt_secret(new_dashscope) if new_dashscope else None

    new_base = payload.embedding_api_base.strip() or None
    if new_base:
        validate_embedding_api_base(new_base)
    if new_base != row.embedding_api_base:
        changed.append("embedding_api_base")
    row.embedding_api_base = new_base

    if bool(payload.llm_mock) != bool(row.llm_mock):
        changed.append("llm_mock")
    row.llm_mock = payload.llm_mock

    await db.flush()
    return changed


# ── 运行时解析（llm_service / rag_service 使用）──


async def get_runtime_config() -> RuntimeLlmConfig | None:
    """读取库内配置的运行时视图；无行/DB 失败返回 None（调用方回退 env）."""
    global _runtime_cache
    now = time.monotonic()
    if _runtime_cache is not None:
        cached_at, cached_cfg = _runtime_cache
        ttl = RUNTIME_CACHE_TTL if cached_cfg is not None else FAILURE_CACHE_TTL
        if now - cached_at < ttl:
            return cached_cfg

    cfg: RuntimeLlmConfig | None = None
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(LlmSetting).limit(1))
            row = result.scalar_one_or_none()
        if row is not None:
            cfg = RuntimeLlmConfig(
                deepseek_api_key=_decrypt_or_empty(row.deepseek_api_key_enc) or None,
                dashscope_api_key=_decrypt_or_empty(row.dashscope_api_key_enc) or None,
                embedding_api_base=row.embedding_api_base,
                llm_mock=bool(row.llm_mock),
            )
    except Exception:
        logger.warning("读取 LLM 页面配置失败，回退环境变量", exc_info=True)
        cfg = None

    _runtime_cache = (now, cfg)
    return cfg


async def is_mock_enabled(mock: bool | None = None) -> bool:
    """mock 判定：显式参数优先；否则 settings.llm_mock 或库内 llm_mock 任一为 true."""
    if mock is not None:
        return mock
    if settings.llm_mock:
        return True
    cfg = await get_runtime_config()
    return bool(cfg is not None and cfg.llm_mock)


# ── 连通性测试（POST /settings/llm/test）──


async def test_connection(target: str) -> dict[str, Any]:
    """真实调用 litellm 验证配置；异常全捕获，永不抛出（api 层恒 200）."""
    if target == "llm":
        return await _test_llm()
    return await _test_embedding()


async def _test_llm() -> dict[str, Any]:
    cfg = await get_runtime_config()
    model = settings.llm_primary
    api_key = cfg.api_key_for(model) if cfg else None
    if settings.llm_mock or (cfg is not None and cfg.llm_mock) or not api_key:
        return {"ok": False, "error": _NOT_CONFIGURED_ERROR}
    try:
        from litellm import acompletion

        start = time.perf_counter()
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            await acompletion(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                api_key=api_key,
            )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {"ok": True, "model": model, "latency_ms": latency_ms}
    except Exception as e:
        return {"ok": False, "error": f"调用失败: {e}"[:200]}


async def _test_embedding() -> dict[str, Any]:
    cfg = await get_runtime_config()
    if settings.llm_mock or (cfg is not None and cfg.llm_mock):
        return {"ok": False, "error": _NOT_CONFIGURED_ERROR}
    api_base = (cfg.embedding_api_base if cfg else None) or settings.embedding_api_base
    api_key = cfg.api_key_for(settings.embedding_model) if cfg else None
    try:
        from litellm import aembedding

        kwargs: dict[str, Any] = {
            "model": settings.embedding_model,
            "input": ["测试"],
            "api_base": api_base,
        }
        if api_key:
            kwargs["api_key"] = api_key
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            response = await aembedding(**kwargs)
        return {"ok": True, "dimension": len(response.data[0]["embedding"])}
    except Exception as e:
        return {"ok": False, "error": f"调用失败: {e}"[:200]}
