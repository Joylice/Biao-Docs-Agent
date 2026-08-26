"""llm_service.call_llm_with_schema 供应商兼容测试 — DeepSeek json_schema 降级（三期 S5 验收修复）.

背景：DeepSeek 兼容接口不支持 strict json_schema（返回
"This response_format type is unavailable now"），仅支持 json_object。
契约：deepseek 模型 + json_schema → 降级 json_object 且 schema 约束写入 system prompt；
非 deepseek 模型保持原样。
"""

import sys
from unittest.mock import MagicMock

import pytest

from app.services.llm.llm_service import call_llm_with_schema

_JSON_SCHEMA_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "demo",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"score_points": {"type": "array"}},
            "required": ["score_points"],
        },
    },
}


def _completion(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


async def _false(mock: bool | None = None) -> bool:
    return False


async def _no_key(_model: str) -> dict:
    return {}


@pytest.fixture
def real_mode(monkeypatch):
    """真实模式 + 隔离 DB：注入假 litellm，返回 captured kwargs."""
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _completion('{"score_points": []}')

    mock_litellm = MagicMock()
    mock_litellm.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", mock_litellm)
    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _false)
    monkeypatch.setattr("app.services.llm.llm_service._api_key_kwargs", _no_key)
    return captured


class TestDeepseekJsonSchemaDowngrade:
    """deepseek 模型：json_schema 降级为 json_object + schema 进 prompt."""

    @pytest.mark.asyncio
    async def test_downgrades_to_json_object(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr("app.services.llm.llm_service.settings.llm_model", "deepseek/deepseek-chat")
        result = await call_llm_with_schema(
            "s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False
        )
        assert result == {"score_points": []}
        assert real_mode["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_schema_constraint_injected_into_system_prompt(
        self, real_mode, monkeypatch
    ) -> None:
        monkeypatch.setattr("app.services.llm.llm_service.settings.llm_model", "deepseek/deepseek-chat")
        await call_llm_with_schema(
            "orig-system", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False
        )
        system = next(m["content"] for m in real_mode["messages"] if m["role"] == "system")
        assert system.startswith("orig-system"), "原 system prompt 保留在前"
        assert "score_points" in system, "schema 结构写入 prompt 约束输出"

    @pytest.mark.asyncio
    async def test_json_object_format_passthrough(self, real_mode, monkeypatch) -> None:
        """已是 json_object 的格式不做改动."""
        monkeypatch.setattr("app.services.llm.llm_service.settings.llm_model", "deepseek/deepseek-chat")
        await call_llm_with_schema("s", "u", response_format={"type": "json_object"}, mock=False)
        assert real_mode["response_format"] == {"type": "json_object"}


class TestNonDeepseekKeepsJsonSchema:
    """非 deepseek 模型：json_schema 原样透传."""

    @pytest.mark.asyncio
    async def test_keeps_json_schema(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr("app.services.llm.llm_service.settings.llm_model", "qwen/qwen-plus")
        await call_llm_with_schema("s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False)
        assert real_mode["response_format"] == _JSON_SCHEMA_FORMAT
