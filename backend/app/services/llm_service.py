"""LLM 调用服务（LiteLLM 封装）."""

from typing import Any

from app.core.config import settings
from app.core.exceptions import LLMServiceError
from app.core.redact import redact

_MOCK_TEXT = (
    "（mock 模式）本节内容为离线 mock 占位文本，用于测试环境下生成链路的完整流程验证。"
    "本方案采用微服务架构，覆盖需求分析、总体设计、开发实施、测试验收与运维保障各阶段，"
    "逐条响应招标文件的技术要求与评分标准，并配套明确的交付物清单、质量保障措施与进度计划，"
    "确保项目按期高质量交付。"
    "本节内容涵盖系统架构、功能实现、安全设计与培训支持等主要环节，"
    "满足招标方对可靠性、可扩展性与可维护性的要求，并提供全生命周期的技术支持与运维服务。"
)


def _is_mock_mode(mock: bool | None) -> bool:
    """判断是否启用 mock：函数参数优先，其次运行时读取 settings.llm_mock."""
    return settings.llm_mock if mock is None else mock


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


async def call_llm_with_schema(
    system_prompt: str,
    user_prompt: str,
    response_format: dict | None = None,
    mock: bool | None = None,
) -> dict:
    """调用 LLM 并解析 JSON 响应."""
    user_prompt = redact(user_prompt)  # 外发 LLM 脱敏（安全铁律，出口兜底，无开关）
    if _is_mock_mode(mock):
        return _mock_schema_response(response_format)
    try:
        from litellm import acompletion

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": 0.1,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await acompletion(**kwargs)
        content = response.choices[0].message.content

        # 解析 JSON
        import json

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
    if _is_mock_mode(mock):
        return _MOCK_TEXT
    try:
        from litellm import acompletion

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await acompletion(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise LLMServiceError(f"LLM 调用失败: {e}") from None
