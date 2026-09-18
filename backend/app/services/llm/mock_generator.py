"""Mock 模式响应生成器（P1-6 拆分自 llm_service.py）.

mock 模式短路真实调用：schema 响应按 JSON Schema 递归生成稳定占位值，
文本/流式响应返回固定 _MOCK_TEXT。
"""

from typing import Any

MOCK_TEXT = (
    "（mock 模式）本节内容为离线 mock 占位文本，用于测试环境下生成链路的完整流程验证。"
    "本方案采用微服务架构，覆盖需求分析、总体设计、开发实施、测试验收与运维保障各阶段，"
    "逐条响应招标文件的技术要求与评分标准，并配套明确的交付物清单、质量保障措施与进度计划，"
    "确保项目按期高质量交付。"
    "本节内容涵盖系统架构、功能实现、安全设计与培训支持等主要环节，"
    "满足招标方对可靠性、可扩展性与可维护性的要求，并提供全生命周期的技术支持与运维服务。"
)

MOCK_STREAM_SLICE = 20  # mock 流式切片长度（字符）


def mock_value_from_schema(schema: dict[str, Any]) -> Any:
    """按 JSON schema 递归生成稳定的 mock 值（数组固定生成 1 个元素）."""
    schema_type = schema.get("type")
    if schema_type == "object":
        return {
            key: mock_value_from_schema(prop) for key, prop in schema.get("properties", {}).items()
        }
    if schema_type == "array":
        return [mock_value_from_schema(schema.get("items", {}))]
    if schema_type == "string":
        return "mock"
    if schema_type == "number":
        return 1.0
    if schema_type == "integer":
        return 1
    if schema_type == "boolean":
        return False
    return None


def mock_schema_response(response_format: dict[str, Any] | None) -> dict[str, Any]:
    """mock 模式下按 response_format.json_schema.schema 构造响应."""
    if not response_format:
        return {}
    schema = response_format.get("json_schema", {}).get("schema")
    if not isinstance(schema, dict):
        return {}
    value = mock_value_from_schema(schema)
    return value if isinstance(value, dict) else {}
