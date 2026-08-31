"""LLM 调用可观测性测试：耗时/成败/usage 结构化日志（acompletion 统一调用点）."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import LLMServiceError
from app.services.llm.llm_service import call_llm_text, call_llm_with_schema


def _response(text: str, usage: SimpleNamespace | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=text)
    r = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    if usage is not None:
        r.usage = usage
    return r


def _install_fake_litellm(monkeypatch, response=None, error=None):
    """安装 fake litellm：response 或 error 二选一."""

    async def fake_acompletion(**kwargs):
        if error is not None:
            raise error
        return response

    fake = MagicMock()
    fake.acompletion = fake_acompletion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def _mock_runtime_config(monkeypatch) -> None:
    """resolve_llm_target 走默认路径（无库内配置）."""
    monkeypatch.setattr(
        "app.services.infra.settings_service.get_runtime_config",
        AsyncMock(return_value=None),
    )


class TestCallObservability:
    """call_llm_text / call_llm_with_schema 的观测日志."""

    @pytest.mark.asyncio
    async def test_success_logs_info_with_usage(self, monkeypatch, caplog) -> None:
        """成功路径：info 日志含 kind/model/ok=true/duration/usage."""
        import logging

        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        _install_fake_litellm(monkeypatch, response=_response("回答内容", usage))
        _mock_runtime_config(monkeypatch)
        with caplog.at_level(logging.INFO, logger="app.services.llm.llm_service"):
            text = await call_llm_text("s", "u", mock=False)
        assert text == "回答内容"
        records = [r for r in caplog.records if "llm_call" in r.getMessage()]
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "kind=text" in msg
        assert "ok=true" in msg
        assert "duration_ms=" in msg
        assert "prompt_chars=1" in msg  # user_prompt 脱敏后长度
        assert "prompt_tokens=100" in msg
        assert "completion_tokens=50" in msg
        assert "total_tokens=150" in msg

    @pytest.mark.asyncio
    async def test_success_without_usage_logs_empty(self, monkeypatch, caplog) -> None:
        """响应无 usage 字段（如部分兼容接口）：usage= 空，不报错."""
        import logging

        _install_fake_litellm(monkeypatch, response=_response("ok"))
        _mock_runtime_config(monkeypatch)
        with caplog.at_level(logging.INFO, logger="app.services.llm.llm_service"):
            await call_llm_text("s", "u", mock=False)
        records = [r for r in caplog.records if "llm_call" in r.getMessage()]
        assert records and "usage=" in records[0].getMessage()

    @pytest.mark.asyncio
    async def test_failure_logs_warning_and_raises(self, monkeypatch, caplog) -> None:
        """失败路径：warning 日志 ok=false + error 信息，异常仍上抛为 LLMServiceError."""
        import logging

        _install_fake_litellm(monkeypatch, error=RuntimeError("timeout"))
        _mock_runtime_config(monkeypatch)
        with (
            caplog.at_level(logging.WARNING, logger="app.services.llm.llm_service"),
            pytest.raises(LLMServiceError, match="timeout"),
        ):
            await call_llm_text("s", "u", mock=False)
        records = [r for r in caplog.records if "llm_call" in r.getMessage()]
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "kind=text" in msg
        assert "ok=false" in msg
        assert "error=" in msg

    @pytest.mark.asyncio
    async def test_schema_kind_logged(self, monkeypatch, caplog) -> None:
        """call_llm_with_schema 记录 kind=schema 且 JSON 解析正常."""
        import logging

        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        _install_fake_litellm(
            monkeypatch,
            response=_response('{"comments": [{"chapter_no": "1"}]}', usage),
        )
        _mock_runtime_config(monkeypatch)
        with caplog.at_level(logging.INFO, logger="app.services.llm.llm_service"):
            result = await call_llm_with_schema(
                "s", "u", response_format={"type": "json_object"}, mock=False
            )
        assert result == {"comments": [{"chapter_no": "1"}]}
        records = [r for r in caplog.records if "llm_call" in r.getMessage()]
        assert records and "kind=schema" in records[0].getMessage()
