"""LLM 运行时配置解析 — 库内优先/环境变量回退、进程内缓存、mock 判定、调用目标解析.

从原 settings_service 拆分（第一轮模块拆分）：本模块持有 `_runtime_cache` 缓存状态
（含 invalidate_runtime_cache），是 monkeypatch 打补丁的目标命名空间。

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

import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.llm_settings import LlmSetting

from . import security as _security

logger = logging.getLogger(__name__)

# 运行时配置缓存：(monotonic 时间戳, 配置；None 表示无行/DB 失败)
_runtime_cache: tuple[float, "RuntimeLlmConfig | None"] | None = None
RUNTIME_CACHE_TTL = 30.0  # 秒：正常缓存有效期
FAILURE_CACHE_TTL = 5.0  # 秒：无行/DB 失败的负缓存（避免频繁查库/重连）

# Provider 别名映射：非 LiteLLM 原生支持但 OpenAI 兼容的提供商
# key=用户配置的前缀，value=(litellm provider, 默认 api_base)
# 密钥匹配仍用原始前缀（api_key_for），调用时转换为 litellm 可识别格式
_PROVIDER_ALIASES: dict[str, tuple[str, str]] = {
    "zhipu": ("openai", "https://open.bigmodel.cn/api/paas/v4"),
    "glm": ("openai", "https://open.bigmodel.cn/api/paas/v4"),
    "moonshot": ("openai", "https://api.moonshot.cn/v1"),
    "kimi": ("openai", "https://api.moonshot.cn/v1"),
    "deepseek": ("deepseek", "https://api.deepseek.com/v1"),
}


@dataclass
class RuntimeLlmConfig:
    """llm_settings 解密后的运行时视图."""

    deepseek_api_key: str | None = None
    dashscope_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    zhipu_api_key: str | None = None
    moonshot_api_key: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None
    # 自定义端点（llm_api_base）专用密钥：仅用于该端点，不参与云端密钥匹配
    llm_api_key: str | None = None
    embedding_api_base: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    llm_mock: bool = False

    def api_key_for(self, model: str) -> str | None:
        """按模型前缀匹配库内密钥."""
        if model.startswith("deepseek"):
            return self.deepseek_api_key
        if model.startswith("qwen") or model.startswith("dashscope"):
            return self.dashscope_api_key
        if model.startswith("openai") or model.startswith("gpt"):
            return self.openai_api_key
        if model.startswith("anthropic") or model.startswith("claude"):
            return self.anthropic_api_key
        if model.startswith("zhipu") or model.startswith("glm"):
            return self.zhipu_api_key
        if model.startswith("moonshot") or model.startswith("kimi"):
            return self.moonshot_api_key
        return None


def invalidate_runtime_cache() -> None:
    """清空运行时配置缓存（api 层 commit 成功后调用，本进程即时生效）."""
    global _runtime_cache
    _runtime_cache = None


async def get_runtime_config() -> RuntimeLlmConfig | None:
    """读取库内配置的运行时视图；无行/DB 失败时回退环境变量配置.

    回退策略（测试环境/发版场景）：
    - 数据库有 llm_settings 行 → 使用库内配置（用户在页面修改的优先）
    - 数据库无行/DB 不可达 → 从环境变量构建 RuntimeLlmConfig（BID_LLM_*、BID_*_API_KEY）
    - 环境变量也全空 → 返回 None（调用方退回 settings 默认值）
    """
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
                deepseek_api_key=_security._decrypt_or_empty(row.deepseek_api_key_enc) or None,
                dashscope_api_key=_security._decrypt_or_empty(row.dashscope_api_key_enc) or None,
                openai_api_key=_security._decrypt_or_empty(row.openai_api_key_enc) or None,
                anthropic_api_key=_security._decrypt_or_empty(row.anthropic_api_key_enc) or None,
                zhipu_api_key=_security._decrypt_or_empty(row.zhipu_api_key_enc) or None,
                moonshot_api_key=_security._decrypt_or_empty(row.moonshot_api_key_enc) or None,
                llm_model=row.llm_model,
                llm_api_base=row.llm_api_base,
                llm_api_key=_security._decrypt_or_empty(row.llm_api_key_enc) or None,
                embedding_api_base=row.embedding_api_base,
                embedding_model=row.embedding_model,
                embedding_api_key=_security._decrypt_or_empty(row.embedding_api_key_enc) or None,
                llm_mock=bool(row.llm_mock),
            )
    except Exception:
        logger.warning("读取 LLM 页面配置失败，回退环境变量", exc_info=True)
        cfg = None

    # 数据库无配置时，从环境变量构建（测试环境固化配置，发版无需手动设置）
    if cfg is None:
        env_cfg = _build_config_from_env()
        if env_cfg is not None:
            logger.info("数据库无 LLM 配置，使用环境变量回退配置（model=%s）", env_cfg.llm_model)
            cfg = env_cfg

    _runtime_cache = (now, cfg)
    return cfg


def _build_config_from_env() -> RuntimeLlmConfig | None:
    """从环境变量构建 RuntimeLlmConfig；所有关键字段均为空时返回 None.

    仅检查**显式端点/密钥类**字段（默认值均为 ""）：llm_model / embedding_model /
    embedding_api_base 有非空默认值，不能作为"已显式配置"的依据，否则 DB 无行时
    会被默认值误触发回退（破坏原"无行返回 None"语义）。
    """
    has_any = any([
        settings.llm_api_base,
        settings.llm_api_key,
        settings.deepseek_api_key,
        settings.dashscope_api_key,
        settings.openai_api_key,
        settings.anthropic_api_key,
        settings.zhipu_api_key,
        settings.moonshot_api_key,
        settings.embedding_api_key,
    ])
    if not has_any:
        return None
    return RuntimeLlmConfig(
        deepseek_api_key=settings.deepseek_api_key or None,
        dashscope_api_key=settings.dashscope_api_key or None,
        openai_api_key=settings.openai_api_key or None,
        anthropic_api_key=settings.anthropic_api_key or None,
        zhipu_api_key=settings.zhipu_api_key or None,
        moonshot_api_key=settings.moonshot_api_key or None,
        llm_model=settings.llm_model or None,
        llm_api_base=settings.llm_api_base or None,
        llm_api_key=settings.llm_api_key or None,
        embedding_api_base=settings.embedding_api_base or None,
        embedding_model=settings.embedding_model or None,
        embedding_api_key=settings.embedding_api_key or None,
        llm_mock=bool(settings.llm_mock),
    )


async def is_mock_enabled(mock: bool | None = None) -> bool:
    """mock 判定：显式参数优先；否则 settings.llm_mock 或库内 llm_mock 任一为 true."""
    if mock is not None:
        return mock
    if settings.llm_mock:
        return True
    cfg = await get_runtime_config()
    return bool(cfg is not None and cfg.llm_mock)


async def resolve_llm_target() -> tuple[str, str | None, dict[str, str]]:
    """解析运行时 LLM 调用目标：返回 (litellm_model, api_base, extra_kwargs).

    页面"切换模型"生效路径（llm_service 与连通性测试共用，单一来源）：
    - 库内 llm_model 优先（页面配置）；空则回退 env settings.llm_model（现状）
    - 模型名无 provider 前缀时自动补 ``openai/``（OpenAI 兼容端点通用前缀；
      litellm>=1.97 实测 ``openai_like/`` 解析成功但实际调用报 Unmapped provider）
    - Provider 别名转换：zhipu/moonshot 等非 LiteLLM 原生支持的 OpenAI 兼容
      提供商，自动转换为 ``openai/`` 前缀并注入默认 api_base；用户自定义
      llm_api_base 优先于默认值
    - 自定义端点（llm_api_base 非空）：优先使用页面配置的 **端点专用密钥**
      ``llm_api_key``；未配置时以 ``"EMPTY"`` 占位（vLLM/Ollama 等无认证
      OpenAI 兼容服务通用做法，避免 litellm 报缺 key）。
      安全约束：自定义端点 **绝不回退** deepseek/dashscope 云端密钥，
      防止用户云端凭据被转发至第三方端点。
    - 非自定义端点：按模型前缀匹配库内密钥（deepseek/qwen/zhipu 等前缀）
    """
    cfg = await get_runtime_config()
    if cfg is None or not cfg.llm_model:
        # 回退 env：保持现有行为（按前缀匹配密钥）
        model = settings.llm_model
        key = cfg.api_key_for(model) if cfg else None
        kwargs: dict[str, str] = {"api_key": key} if key else {}
        return model, None, kwargs

    model = cfg.llm_model
    # 解析 provider 前缀，做别名转换
    litellm_model = model
    alias_api_base: str | None = None
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in _PROVIDER_ALIASES:
            litellm_provider, default_base = _PROVIDER_ALIASES[prefix]
            model_name = model.split("/", 1)[1]
            litellm_model = f"{litellm_provider}/{model_name}"
            alias_api_base = default_base
    else:
        litellm_model = f"openai/{model}"

    kwargs: dict[str, str] = {}
    # api_base 优先级：用户自定义 llm_api_base > 别名默认 api_base
    effective_api_base = cfg.llm_api_base or alias_api_base
    if effective_api_base:
        # 自定义端点或别名端点：使用对应密钥
        if cfg.llm_api_base:
            # 用户显式配置的自定义端点：只认端点专用密钥，不回退云端密钥
            kwargs["api_base"] = cfg.llm_api_base
            kwargs["api_key"] = cfg.llm_api_key or "EMPTY"
        else:
            # 别名默认端点：按原始前缀匹配密钥
            kwargs["api_base"] = alias_api_base  # type: ignore[assignment]
            key = cfg.api_key_for(cfg.llm_model)
            if key:
                kwargs["api_key"] = key
    else:
        # 无 api_base：按模型前缀匹配密钥（deepseek/dashscope/openai 等原生 provider）
        key = cfg.api_key_for(cfg.llm_model)
        if key:
            kwargs["api_key"] = key
    return litellm_model, effective_api_base, kwargs
