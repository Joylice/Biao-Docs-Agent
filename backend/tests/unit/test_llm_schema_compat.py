"""llm_service.call_llm_with_schema 供应商兼容测试 — 非 OpenAI 原生模型 json_schema 降级（三期 S5 验收修复）.

背景：DeepSeek / 智谱 / 月之暗面等 OpenAI 兼容接口不支持 strict json_schema
（返回 "This response_format type is unavailable now" 或静默返回空），仅支持
json_object。契约：非 OpenAI 原生模型 + json_schema → 降级 json_object 且 schema
约束写入 system prompt；openai/gpt 原生模型保持原样。
"""

import sys
from unittest.mock import MagicMock

import pytest

from app.core.config import settings as app_settings
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


async def _no_runtime_config():
    """无库内配置 → resolve_llm_target 回退 env 且不注入 api_key."""
    return None


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
    monkeypatch.setattr(
        "app.services.infra.settings_service.get_runtime_config", _no_runtime_config
    )
    return captured


class TestDeepseekJsonSchemaDowngrade:
    """deepseek 模型：json_schema 降级为 json_object + schema 进 prompt."""

    @pytest.mark.asyncio
    async def test_downgrades_to_json_object(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr(app_settings, "llm_model", "deepseek/deepseek-chat")
        result = await call_llm_with_schema(
            "s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False
        )
        assert result == {"score_points": []}
        assert real_mode["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_schema_constraint_injected_into_system_prompt(
        self, real_mode, monkeypatch
    ) -> None:
        monkeypatch.setattr(app_settings, "llm_model", "deepseek/deepseek-chat")
        await call_llm_with_schema(
            "orig-system", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False
        )
        system = next(m["content"] for m in real_mode["messages"] if m["role"] == "system")
        assert system.startswith("orig-system"), "原 system prompt 保留在前"
        assert "score_points" in system, "schema 结构写入 prompt 约束输出"

    @pytest.mark.asyncio
    async def test_json_object_format_passthrough(self, real_mode, monkeypatch) -> None:
        """已是 json_object 的格式不做改动."""
        monkeypatch.setattr(app_settings, "llm_model", "deepseek/deepseek-chat")
        await call_llm_with_schema("s", "u", response_format={"type": "json_object"}, mock=False)
        assert real_mode["response_format"] == {"type": "json_object"}


class TestNonOpenAiNativeKeepsJsonSchema:
    """openai/gpt 原生模型：json_schema 原样透传."""

    @pytest.mark.asyncio
    async def test_keeps_json_schema(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr(app_settings, "llm_model", "openai/gpt-4o")
        await call_llm_with_schema("s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False)
        assert real_mode["response_format"] == _JSON_SCHEMA_FORMAT

    @pytest.mark.asyncio
    async def test_gpt_short_name_keeps_json_schema(self, real_mode, monkeypatch) -> None:
        """gpt 前缀（无 openai/ 前缀）同样保持透传."""
        monkeypatch.setattr(app_settings, "llm_model", "gpt-4o")
        await call_llm_with_schema("s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False)
        assert real_mode["response_format"] == _JSON_SCHEMA_FORMAT


class TestCompatModelJsonSchemaDowngrade:
    """兼容接口模型（qwen/zhipu/moonshot 等）：json_schema 降级为 json_object."""

    @pytest.mark.asyncio
    async def test_qwen_downgrades(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr(app_settings, "llm_model", "qwen/qwen-plus")
        await call_llm_with_schema("s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False)
        assert real_mode["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_zhipu_downgrades(self, real_mode, monkeypatch) -> None:
        monkeypatch.setattr(app_settings, "llm_model", "zhipu/glm-4.6v")
        await call_llm_with_schema("s", "u", response_format=_JSON_SCHEMA_FORMAT, mock=False)
        assert real_mode["response_format"] == {"type": "json_object"}
