"""LLM 统一调用点与供应商兼容处理（P1-6 拆分自 llm_service.py）.

- _call_and_log：acompletion 唯一调用点，耗时/成败/usage 观测 + 用量落库；
- _compat_response_format：非 OpenAI 原生模型 json_schema → json_object 降级；
- _apply_route_params：路由行参数合入调用 kwargs。
"""

import json
import time
from typing import Any

from app.services.llm.usage_log import (
    fire_usage_log,
    log_llm_call,
    usage_entry,
    usage_fields,
    usage_summary,
)


def compat_response_format(
    model: str, response_format: dict[str, Any] | None, system_prompt: str
) -> tuple[dict[str, Any] | None, str]:
    """供应商兼容处理：非 OpenAI 原生模型不支持 strict json_schema，
    降级 json_object + schema 入 prompt.

    DeepSeek / 智谱 / 月之暗面等 OpenAI 兼容接口对 response_format 仅支持
    json_object（json_schema 报 "This response_format type is unavailable now"
    或静默返回空）；降级后将 schema 结构写入 system prompt 约束输出，
    OpenAI 原生模型保持原样透传。
    """
    if not response_format or response_format.get("type") != "json_schema":
        return response_format, system_prompt
    # OpenAI 原生模型（gpt 系列）支持 json_schema，保持原样
    if model.startswith("openai") or model.startswith("gpt"):
        return response_format, system_prompt
    schema = response_format.get("json_schema", {}).get("schema", {})
    constraint = (
        "\n\n输出要求：仅输出严格匹配以下 JSON Schema 的 JSON 对象，不得包含任何其他内容：\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    return {"type": "json_object"}, system_prompt + constraint


def apply_route_params(kwargs: dict[str, Any], route_params: dict[str, Any]) -> dict[str, Any]:
    """将路由行参数（max_tokens/timeout）合入调用 kwargs（显式/已有值优先）."""
    for name in ("max_tokens", "timeout"):
        if route_params.get(name) is not None:
            kwargs.setdefault(name, route_params[name])
    return kwargs


async def call_and_log(
    kind: str,
    model: str,
    kwargs: dict[str, Any],
    prompt_chars: int,
    *,
    stage_key: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> Any:
    """acompletion 统一调用点：记录耗时/成败/usage 后返回原始响应.

    成功/失败各异步写一行 llm_usage_log（fire-and-forget，写失败不影响主流程）。
    S5 归因：agent_id/skill_name 透传落库（可空，缺省 None）。
    """
    from litellm import acompletion

    t0 = time.perf_counter()
    try:
        response = await acompletion(**kwargs)
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        log_llm_call(kind, model, elapsed, False, prompt_chars, error=repr(e))
        fire_usage_log(
            usage_entry(
                kind=kind,
                model=model,
                stage_key=stage_key,
                project_id=project_id,
                agent_id=agent_id,
                skill_name=skill_name,
                ok=False,
                elapsed_ms=elapsed,
                error=repr(e),
            )
        )
        raise
    elapsed = (time.perf_counter() - t0) * 1000
    prompt_tokens, completion_tokens, total_tokens = usage_fields(response)
    log_llm_call(
        kind,
        model,
        elapsed,
        True,
        prompt_chars,
        usage=usage_summary(response),
    )
    fire_usage_log(
        usage_entry(
            kind=kind,
            model=model,
            stage_key=stage_key,
            project_id=project_id,
            agent_id=agent_id,
            skill_name=skill_name,
            ok=True,
            elapsed_ms=elapsed,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    return response
