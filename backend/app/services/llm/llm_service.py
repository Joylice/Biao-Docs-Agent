"""LLM 调用服务（LiteLLM 封装）.

运行时配置：mock 判定与 api_key 解析下沉 settings_service ——
库内（llm_settings 页面配置）密钥优先于环境变量；库内无配置则回退 env 现状。
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.exceptions import LLMServiceError
from app.core.redact import redact
from app.services.infra import settings_service

_MOCK_TEXT = (
    "（mock 模式）本节内容为离线 mock 占位文本，用于测试环境下生成链路的完整流程验证。"
    "本方案采用微服务架构，覆盖需求分析、总体设计、开发实施、测试验收与运维保障各阶段，"
    "逐条响应招标文件的技术要求与评分标准，并配套明确的交付物清单、质量保障措施与进度计划，"
    "确保项目按期高质量交付。"
    "本节内容涵盖系统架构、功能实现、安全设计与培训支持等主要环节，"
    "满足招标方对可靠性、可扩展性与可维护性的要求，并提供全生命周期的技术支持与运维服务。"
)


def _mock_value_from_schema(schema: dict[str, Any]) -> Any:
    """按 JSON schema 递归生成稳定的 mock 值（数组固定生成 1 个元素）."""
    schema_type = schema.get("type")
    if schema_type == "object":
        return {
            key: _mock_value_from_schema(prop) for key, prop in schema.get("properties", {}).items()
        }
    if schema_type == "array":
        return [_mock_value_from_schema(schema.get("items", {}))]
    if schema_type == "string":
        return "mock"
    if schema_type == "number":
        return 1.0
    if schema_type == "integer":
        return 1
    if schema_type == "boolean":
        return False
    return None


def _mock_schema_response(response_format: dict | None) -> dict:
    """mock 模式下按 response_format.json_schema.schema 构造响应."""
    if not response_format:
        return {}
    schema = response_format.get("json_schema", {}).get("schema")
    if not isinstance(schema, dict):
        return {}
    value = _mock_value_from_schema(schema)
    return value if isinstance(value, dict) else {}


def _compat_response_format(
    model: str, response_format: dict | None, system_prompt: str
) -> tuple[dict | None, str]:
    """供应商兼容处理：DeepSeek 不支持 strict json_schema，降级 json_object + schema 入 prompt.

    DeepSeek 兼容接口对 response_format 仅支持 json_object（json_schema 报
    "This response_format type is unavailable now"）；降级后将 schema 结构
    写入 system prompt 约束输出，其余模型保持原样透传。
    """
    if not response_format or response_format.get("type") != "json_schema":
        return response_format, system_prompt
    if not model.startswith("deepseek"):
        return response_format, system_prompt
    schema = response_format.get("json_schema", {}).get("schema", {})
    constraint = (
        "\n\n输出要求：仅输出严格匹配以下 JSON Schema 的 JSON 对象，不得包含任何其他内容：\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    return {"type": "json_object"}, system_prompt + constraint


async def call_llm_with_schema(
    system_prompt: str,
    user_prompt: str,
    response_format: dict | None = None,
    mock: bool | None = None,
) -> dict:
    """调用 LLM 并解析 JSON 响应."""
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if await settings_service.is_mock_enabled(mock):
        return _mock_schema_response(response_format)
    try:
        from litellm import acompletion

        model, _api_base, llm_kwargs = await settings_service.resolve_llm_target()
        response_format, system_prompt = _compat_response_format(
            model, response_format, system_prompt
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            **llm_kwargs,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await acompletion(**kwargs)
        content = response.choices[0].message.content

        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMServiceError(f"LLM 返回非 JSON: {e}") from None
    except Exception as e:
        raise LLMServiceError(f"LLM 调用失败: {e}") from None


async def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    mock: bool | None = None,
) -> str:
    """调用 LLM 获取文本响应."""
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if await settings_service.is_mock_enabled(mock):
        return _MOCK_TEXT
    try:
        from litellm import acompletion

        model, _api_base, llm_kwargs = await settings_service.resolve_llm_target()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            **llm_kwargs,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise LLMServiceError(f"LLM 调用失败: {e}") from None


async def chat_with_tools(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    executor: Callable[[str, dict[str, Any]], Awaitable[str]],
    *,
    max_rounds: int = 3,
    temperature: float = 0.3,
    mock: bool | None = None,
) -> tuple[str, list[dict]]:
    """Tool Calling 对话（阶段 F）：解析 tool_calls 循环 ≤ max_rounds 轮.

    mock 模式直通纯文本分支（不触发任何工具，行为等价 call_llm_text）；
    真实模式：acompletion(tools=...) → 解析 tool_calls → executor 执行 →
    结果脱敏后回填续问，直到纯文本收敛或轮数耗尽（不带 tools 强收敛）。
    返回 (最终文本, 调用历史 [{name, arguments, result}])。
    单个工具执行异常回填「工具执行失败」继续对话，不中断循环。
    """
    if await settings_service.is_mock_enabled(mock):
        text = await call_llm_text(system_prompt, user_prompt, temperature, mock=True)
        return text, []
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    try:
        from litellm import acompletion

        model, _api_base, llm_kwargs = await settings_service.resolve_llm_target()
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        calls: list[dict] = []
        for _ in range(max_rounds):
            response = await acompletion(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                **llm_kwargs,
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
        response = await acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            **llm_kwargs,
        )
        return (response.choices[0].message.content or ""), calls
    except Exception as e:
        raise LLMServiceError(f"Tool Calling 调用失败: {e}") from None


_MOCK_STREAM_SLICE = 20  # mock 流式切片长度（字符）


async def call_llm_stream(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    mock: bool | None = None,
    stop_event: asyncio.Event | None = None,
) -> AsyncIterator[str]:
    """调用 LLM 获取流式文本响应（三期 S4）.

    mock 模式：把 _MOCK_TEXT 按 ~20 字切片 yield（含微小 sleep 模拟节奏）；
    真实模式：acompletion(stream=True)，逐 chunk yield delta（跳过空 delta）。
    stop_event（阶段 2）：取消令牌，置位后停止 yield，已产出部分由调用方保留。
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
        from litellm import acompletion

        model, _api_base, llm_kwargs = await settings_service.resolve_llm_target()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            **llm_kwargs,
        )
        async for chunk in response:
            if stop_event is not None and stop_event.is_set():
                return
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as e:
        raise LLMServiceError(f"LLM 流式调用失败: {e}") from None
