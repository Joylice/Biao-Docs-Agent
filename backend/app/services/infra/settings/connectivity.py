"""LLM/Embedding 连通性测试 — 真实调用 litellm（异常全捕获，永不抛出）.

从原 settings_service 拆分（第一轮模块拆分）：本模块只做调用验证，
mock 判定与目标解析复用 runtime 子模块（经模块属性动态引用，保证 monkeypatch 生效）。
"""

import asyncio
import time
from typing import Any

from app.core.config import settings

from . import runtime as _runtime

TEST_TIMEOUT_SECONDS = 15.0  # 连通性测试超时上限
_NOT_CONFIGURED_ERROR = "未配置密钥或处于 mock 模式"


async def test_connection(target: str, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """真实调用 litellm 验证配置；异常全捕获，永不抛出（api 层恒 200）.

    overrides（model/api_base/api_key）携带时按表单未保存值测试（先测后存流程），
    mock 判定跳过（用户显式要求测真实端点）；api_key 缺省回退已保存端点密钥。
    """
    if target == "llm":
        return await _test_llm(overrides)
    return await _test_embedding()


async def _call_llm(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """发起一次 litellm acompletion ping，返回统一结果结构."""
    try:
        from litellm import acompletion

        start = time.perf_counter()
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            await acompletion(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                **kwargs,
            )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {"ok": True, "model": model, "latency_ms": latency_ms}
    except Exception as e:
        return {"ok": False, "error": f"调用失败: {e}"[:200]}


async def _test_llm(overrides: dict[str, str] | None = None) -> dict[str, Any]:
    ov = overrides or {}
    model_override = (ov.get("model") or "").strip()
    if model_override:
        # 覆盖模式：测试表单未保存的值；model 无前缀时按自定义端点惯例补 openai/
        litellm_model = model_override if "/" in model_override else f"openai/{model_override}"
        cfg = await _runtime.get_runtime_config()
        api_key = (ov.get("api_key") or "").strip() or (cfg.llm_api_key if cfg else None)
        kwargs: dict[str, Any] = {"api_key": api_key or "EMPTY"}
        api_base = (ov.get("api_base") or "").strip()
        if api_base:
            kwargs["api_base"] = api_base
        return await _call_llm(litellm_model, kwargs)

    if await _runtime.is_mock_enabled():
        return {"ok": False, "error": _NOT_CONFIGURED_ERROR}
    model, _api_base, kwargs, _route_params = await _runtime.resolve_llm_target()
    # 回退 env 场景必须命中密钥才能测；自定义端点（resolve 已注入 EMPTY 占位）允许无 key
    if not kwargs.get("api_key"):
        return {"ok": False, "error": _NOT_CONFIGURED_ERROR}
    return await _call_llm(model, kwargs)


async def _test_embedding() -> dict[str, Any]:
    cfg = await _runtime.get_runtime_config()
    if settings.llm_mock or (cfg is not None and cfg.llm_mock):
        return {"ok": False, "error": _NOT_CONFIGURED_ERROR}
    # 页面配置的 model/api_base/api_key 优先，回退 env
    model = (cfg.embedding_model if cfg else None) or settings.embedding_model
    # 容错（易用性）：模型名无 LiteLLM provider 前缀时自动补 openai_like/（OpenAI 兼容接口）
    if "/" not in model:
        model = f"openai_like/{model}"
    api_base = (cfg.embedding_api_base if cfg else None) or settings.embedding_api_base
    # 优先 embedding 专用密钥；其次按模型前缀匹配 deepseek/dashscope 密钥；最后回退 env
    api_key = None
    if cfg:
        api_key = cfg.embedding_api_key or cfg.api_key_for(model)
    try:
        from litellm import aembedding

        kwargs: dict[str, Any] = {
            "model": model,
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
