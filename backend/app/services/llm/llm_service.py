"""LLM 调用服务（LiteLLM 封装）— 门面模块.

P1-6 拆分后本模块只保留 4 个公共调用入口（对外接口不变）：
- call_llm_with_schema / call_llm_text / chat_with_tools / call_llm_stream

实现下沉子模块：
- errors.py         错误分类（LLMErrorCategory / classify_llm_error）
- mock_generator.py mock 模式响应生成
- usage_log.py      观测日志 + llm_usage_log fire-and-forget 埋点
- caller.py         acompletion 统一调用点 + 供应商兼容 + 路由参数合入

运行时配置：mock 判定与 api_key 解析下沉 settings_service ——
库内（llm_settings 页面配置）密钥优先于环境变量；库内无配置则回退 env 现状。

Phase 1 模型路由运行时：
- 4 个调用入口均支持 ``stage_key``：经 runtime.resolve_llm_target(stage_key)
  查 model_routes 阶段路由（30s 缓存），未命中回退全局旧逻辑；
- 路由参数优先级：调用方显式参数 > route_params（路由行）> 硬编码默认；
- 每次真实调用（成功/失败各一行）异步 fire-and-forget 写 llm_usage_log；
- 错误分类（LLMErrorCategory）：RETRYABLE 可重试 / FATAL 快速失败并透出根因。
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.exceptions import LLMServiceError
from app.core.redact import redact
from app.services.infra import settings_service

# 子模块实现（下划线别名 = 拆分前内部符号名，保持 monkeypatch/引用兼容）
from app.services.llm.caller import (
    apply_route_params as _apply_route_params,
)
from app.services.llm.caller import (
    call_and_log as _call_and_log,
)
from app.services.llm.caller import (
    compat_response_format as _compat_response_format,
)
from app.services.llm.errors import LLMErrorCategory, classify_llm_error
from app.services.llm.mock_generator import (
    MOCK_STREAM_SLICE as _MOCK_STREAM_SLICE,
)
from app.services.llm.mock_generator import (
    MOCK_TEXT as _MOCK_TEXT,
)
from app.services.llm.mock_generator import (
    mock_schema_response as _mock_schema_response,
)

__all__ = [
    "LLMErrorCategory",
    "call_llm_stream",
    "call_llm_text",
    "call_llm_with_schema",
    "chat_with_tools",
    "classify_llm_error",
]


async def call_llm_with_schema(
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any] | None = None,
    mock: bool | None = None,
    *,
    stage_key: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """调用 LLM 并解析 JSON 响应.

    stage_key：阶段路由键（model_routes）；mock 模式前置短路，不查路由。
    agent_id/skill_name：S5 归因（落 llm_usage_log，可空）。
    temperature 优先级：route_params > 硬编码默认 0.1。
    """
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if await settings_service.is_mock_enabled(mock):
        return _mock_schema_response(response_format)
    try:
        model, _api_base, llm_kwargs, route_params = await settings_service.resolve_llm_target(
            stage_key
        )
        response_format, system_prompt = _compat_response_format(
            model, response_format, system_prompt
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = _apply_route_params(
            {
                "model": model,
                "messages": messages,
                "temperature": route_params.get("temperature", 0.1),
                **llm_kwargs,
            },
            route_params,
        )
        if response_format:
            kwargs["response_format"] = response_format

        response = await _call_and_log(
            "schema",
            model,
            kwargs,
            len(user_prompt),
            stage_key=stage_key,
            project_id=project_id,
            agent_id=agent_id,
            skill_name=skill_name,
        )
        content = response.choices[0].message.content

        # json.loads 返回 Any；显式落到声明返回类型
        parsed: dict[str, Any] = json.loads(content)
        return parsed
    except json.JSONDecodeError as e:
        # FATAL（响应格式错）：message 透出原始根因
        raise LLMServiceError(f"LLM 返回非 JSON: {e}", category=LLMErrorCategory.FATAL) from None
    except Exception as e:
        raise LLMServiceError(f"LLM 调用失败: {e}", category=classify_llm_error(e)) from None


async def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    mock: bool | None = None,
    *,
    stage_key: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> str:
    """调用 LLM 获取文本响应.

    agent_id/skill_name：S5 归因（落 llm_usage_log，可空）。
    temperature 优先级：调用方显式参数 > route_params > 硬编码默认 0.7
    （缺省 None 以区分"未传"与"显式传 0.7"）。
    """
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if await settings_service.is_mock_enabled(mock):
        return _MOCK_TEXT
    try:
        model, _api_base, llm_kwargs, route_params = await settings_service.resolve_llm_target(
            stage_key
        )
        effective_temperature = (
            temperature if temperature is not None else route_params.get("temperature", 0.7)
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await _call_and_log(
            "text",
            model,
            _apply_route_params(
                {
                    "model": model,
                    "messages": messages,
                    "temperature": effective_temperature,
                    **llm_kwargs,
                },
                route_params,
            ),
            len(user_prompt),
            stage_key=stage_key,
            project_id=project_id,
            agent_id=agent_id,
            skill_name=skill_name,
        )
        # litellm 响应的 content 对 mypy 是 Any；显式落到声明返回类型
        text: str = response.choices[0].message.content
        return text
    except Exception as e:
        raise LLMServiceError(f"LLM 调用失败: {e}", category=classify_llm_error(e)) from None


async def chat_with_tools(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    executor: Callable[[str, dict[str, Any]], Awaitable[str]],
    *,
    max_rounds: int = 3,
    temperature: float | None = None,
    mock: bool | None = None,
    stage_key: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Tool Calling 对话（阶段 F）：解析 tool_calls 循环 ≤ max_rounds 轮.

    mock 模式直通纯文本分支（不触发任何工具，行为等价 call_llm_text）；
    真实模式：acompletion(tools=...) → 解析 tool_calls → executor 执行 →
    结果脱敏后回填续问，直到纯文本收敛或轮数耗尽（不带 tools 强收敛）。
    返回 (最终文本, 调用历史 [{name, arguments, result}])。
    单个工具执行异常回填「工具执行失败」继续对话，不中断循环。
    agent_id/skill_name：S5 归因 —— **两条出口（tools_roundN 收敛 / tools_final 耗尽）都落库**。
    temperature 优先级：调用方显式参数 > route_params > 硬编码默认 0.3。
    """
    if await settings_service.is_mock_enabled(mock):
        text = await call_llm_text(
            system_prompt,
            user_prompt,
            temperature,
            mock=True,
            stage_key=stage_key,
            agent_id=agent_id,
            skill_name=skill_name,
        )
        return text, []
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    try:
        model, _api_base, llm_kwargs, route_params = await settings_service.resolve_llm_target(
            stage_key
        )
        effective_temperature = (
            temperature if temperature is not None else route_params.get("temperature", 0.3)
        )
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        calls: list[dict[str, Any]] = []
        for round_no in range(max_rounds):
            response = await _call_and_log(
                f"tools_round{round_no + 1}",
                model,
                _apply_route_params(
                    {
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                        "temperature": effective_temperature,
                        **llm_kwargs,
                    },
                    route_params,
                ),
                len(user_prompt),
                stage_key=stage_key,
                project_id=project_id,
                agent_id=agent_id,
                skill_name=skill_name,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                return (message.content or ""), calls
            messages.append(message)
            for tc in tool_calls:
                name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                try:
                    result = await executor(name, arguments)
                except Exception as e:  # 工具异常回填继续，不中断对话
                    result = f"工具执行失败: {e}"
                result = redact(result)  # 工具结果同属外发内容，回填前脱敏
                calls.append({"name": name, "arguments": arguments, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        # 轮数耗尽：不带 tools 收敛最终答复
        response = await _call_and_log(
            "tools_final",
            model,
            _apply_route_params(
                {
                    "model": model,
                    "messages": messages,
                    "temperature": effective_temperature,
                    **llm_kwargs,
                },
                route_params,
            ),
            len(user_prompt),
            stage_key=stage_key,
            project_id=project_id,
            agent_id=agent_id,
            skill_name=skill_name,
        )
        return (response.choices[0].message.content or ""), calls
    except Exception as e:
        raise LLMServiceError(
            f"Tool Calling 调用失败: {e}", category=classify_llm_error(e)
        ) from None


async def call_llm_stream(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    mock: bool | None = None,
    stop_event: asyncio.Event | None = None,
    *,
    stage_key: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> AsyncIterator[str]:
    """调用 LLM 获取流式文本响应（三期 S4）.

    agent_id/skill_name：S5 归因（落 llm_usage_log，可空）。
    mock 模式：把 _MOCK_TEXT 按 ~20 字切片 yield（含微小 sleep 模拟节奏）；
    真实模式：acompletion(stream=True)，逐 chunk yield delta（跳过空 delta）。
    stop_event（阶段 2）：取消令牌，置位后停止 yield，已产出部分由调用方保留。
    temperature 优先级：调用方显式参数 > route_params > 硬编码默认 0.7。
    """
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if await settings_service.is_mock_enabled(mock):
        for i in range(0, len(_MOCK_TEXT), _MOCK_STREAM_SLICE):
            if stop_event is not None and stop_event.is_set():
                return
            yield _MOCK_TEXT[i : i + _MOCK_STREAM_SLICE]
            await asyncio.sleep(0.01)
        return
    try:
        model, _api_base, llm_kwargs, route_params = await settings_service.resolve_llm_target(
            stage_key
        )
        effective_temperature = (
            temperature if temperature is not None else route_params.get("temperature", 0.7)
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await _call_and_log(
            "stream",
            model,
            _apply_route_params(
                {
                    "model": model,
                    "messages": messages,
                    "temperature": effective_temperature,
                    "stream": True,
                    **llm_kwargs,
                },
                route_params,
            ),
            len(user_prompt),
            stage_key=stage_key,
            project_id=project_id,
            agent_id=agent_id,
            skill_name=skill_name,
        )
        async for chunk in response:
            if stop_event is not None and stop_event.is_set():
                return
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as e:
        raise LLMServiceError(f"LLM 流式调用失败: {e}", category=classify_llm_error(e)) from None
