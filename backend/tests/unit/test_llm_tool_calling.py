"""阶段 F：llm_service.chat_with_tools 测试 — tool_call 解析循环（≤3 轮）."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm_service import _MOCK_TEXT, chat_with_tools


def _tool_message(tool_calls: list) -> SimpleNamespace:
    """acompletion 响应：assistant 请求工具调用."""
    message = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _text_message(text: str) -> SimpleNamespace:
    """acompletion 响应：纯文本收敛."""
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class TestMockPassthrough:
    """mock 模式直通纯文本分支（不触发任何工具，行为等价 call_llm_text）."""

    @pytest.mark.asyncio
    async def test_mock_returns_text_without_tools(self) -> None:
        executor = AsyncMock()
        text, calls = await chat_with_tools("s", "u", tools=[], executor=executor, mock=True)
        assert text == _MOCK_TEXT
        assert calls == []
        executor.assert_not_called()


class TestToolLoop:
    """真实模式：tool_calls → executor → tool 消息回填 → 收敛."""

    @pytest.mark.asyncio
    async def test_executes_tool_then_final_answer(self, monkeypatch) -> None:
        responses = [
            _tool_message([_call("c1", "kb_search", '{"query": "架构"}')]),
            _text_message("最终答复"),
        ]
        seen: list[dict] = []

        async def fake_acompletion(**kwargs):
            seen.append(kwargs)
            return responses[len(seen) - 1]

        fake_litellm = MagicMock()
        fake_litellm.acompletion = fake_acompletion
        monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
        monkeypatch.setattr("app.services.llm_service._api_key_kwargs", AsyncMock(return_value={}))

        executor = AsyncMock(return_value='[{"content": "素材"}]')
        text, calls = await chat_with_tools(
            "s",
            "u",
            tools=[{"type": "function", "function": {"name": "kb_search"}}],
            executor=executor,
            mock=False,
        )

        assert text == "最终答复"
        assert len(calls) == 1
        assert calls[0]["name"] == "kb_search"
        assert calls[0]["arguments"] == {"query": "架构"}
        executor.assert_awaited_once_with("kb_search", {"query": "架构"})
        # 首轮请求携带 tools；第二轮消息含 tool 结果回填
        assert seen[0]["tools"]
        assert seen[1]["messages"][-1]["role"] == "tool"
        assert seen[1]["messages"][-1]["tool_call_id"] == "c1"

    @pytest.mark.asyncio
    async def test_executor_failure_fed_back_not_raised(self, monkeypatch) -> None:
        """工具执行异常：结果回填「工具执行失败」继续对话，不中断循环."""
        responses = [
            _tool_message([_call("c1", "kb_search", "{}")]),
            _text_message("降级答复"),
        ]
        seen: list[dict] = []

        async def fake_acompletion(**kwargs):
            seen.append(kwargs)
            return responses[len(seen) - 1]

        fake_litellm = MagicMock()
        fake_litellm.acompletion = fake_acompletion
        monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
        monkeypatch.setattr("app.services.llm_service._api_key_kwargs", AsyncMock(return_value={}))

        executor = AsyncMock(side_effect=RuntimeError("boom"))
        text, calls = await chat_with_tools(
            "s",
            "u",
            tools=[{"type": "function"}],
            executor=executor,
            mock=False,
        )
        assert text == "降级答复"
        assert "工具执行失败" in calls[0]["result"]

    @pytest.mark.asyncio
    async def test_rounds_capped_then_converge(self, monkeypatch) -> None:
        """模型持续请求工具：≤ max_rounds 轮后不带 tools 收敛最终答复."""
        count = {"n": 0}

        async def fake_acompletion(**kwargs):
            count["n"] += 1
            if count["n"] <= 3:
                return _tool_message([_call(f"c{count['n']}", "kb_search", '{"query": "q"}')])
            assert "tools" not in kwargs, "收敛轮不应再携带 tools"
            return _text_message("收敛答复")

        fake_litellm = MagicMock()
        fake_litellm.acompletion = fake_acompletion
        monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
        monkeypatch.setattr("app.services.llm_service._api_key_kwargs", AsyncMock(return_value={}))

        executor = AsyncMock(return_value="[]")
        text, calls = await chat_with_tools(
            "s",
            "u",
            tools=[{"type": "function"}],
            executor=executor,
            max_rounds=3,
            mock=False,
        )
        assert text == "收敛答复"
        assert len(calls) == 3
        assert count["n"] == 4
