"""S5 归因透传与聚合测试 —— skill_name/agent_id 从契约到 llm_usage_log 落库.

覆盖面（改造计划 §六「五处透传」+ 产出接口）：
1. usage_entry：新增 agent_id/skill_name 两个可选键（默认 None 向后兼容）；
2. caller.call_and_log：成功/失败两条 fire 路径都透传两键；
3. llm_service 四入口：skill_name kwarg → _call_and_log（shim 别名，patch 服务模块全局名）；
4. 🔴 验收锚点：chat_with_tools 两条出口（tools_roundN 正常收敛 / tools_final 轮数耗尽）
   都落 skill_name —— 「改完准则看指标」的闭环只在这两行数据上成立；
5. prompts.load_agent_skill_prompt：返回三元组（skill 名来自 contract.name，YAML 回退为 None）；
6. usage_service.skill_profiles：按 skill_name 聚合（NULL→unknown），含 failed_calls；
7. GET /usage/skill-profiles 端点契约。

测试策略：本机无 PostgreSQL —— _call_and_log/fire_usage_log 用 monkeypatch 捕获，
聚合用 FakeSession.execute 返回预设行（零真连）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.llm import llm_service
from app.services.llm.usage_log import usage_entry

# ────────────────────────── 1. usage_entry 归因键 ──────────────────────────


class TestUsageEntryAttribution:
    def test_entry_carries_skill_and_agent(self) -> None:
        """显式传 skill_name/agent_id → 原样落 dict（落库列来源）."""
        entry = usage_entry(
            kind="schema",
            model="deepseek/deepseek-chat",
            stage_key="parse",
            project_id=None,
            ok=True,
            elapsed_ms=123.4,
            agent_id="score_agent",
            skill_name="parse_score",
        )
        assert entry["skill_name"] == "parse_score"
        assert entry["agent_id"] == "score_agent"

    def test_entry_defaults_none(self) -> None:
        """不传两键 → None（既有调用方零改动向后兼容，迁移前列值合法）."""
        entry = usage_entry(
            kind="text",
            model="m",
            stage_key="parse",
            project_id=None,
            ok=False,
            elapsed_ms=1.0,
        )
        assert entry["skill_name"] is None
        assert entry["agent_id"] is None


# ────────────────────────── 2. call_and_log 透传 ──────────────────────────


class TestCallAndLogPassthrough:
    @pytest.fixture()
    def captured(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """捕获 fire_usage_log 的 entry（成功/失败两条 fire 路径共用）."""
        fired: list[dict[str, Any]] = []

        async def fake_acompletion(**_kwargs: Any) -> Any:
            msg = SimpleNamespace(content='{"ok": 1}', tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

        monkeypatch.setattr("litellm.acompletion", fake_acompletion)
        # 🔴 铁律⑩：caller.py 是模块级 `from usage_log import fire_usage_log`，
        # patch 必须打调用方模块全局名 caller.fire_usage_log（patch 真模块不生效）。
        import app.services.llm.caller as caller_mod

        monkeypatch.setattr(caller_mod, "fire_usage_log", lambda entry: fired.append(entry))
        return fired

    def test_success_entry_carries_attribution(self, captured: list[dict[str, Any]]) -> None:
        from app.services.llm.caller import call_and_log

        asyncio.run(
            call_and_log(
                "schema",
                "m",
                {"model": "m", "messages": []},
                10,
                stage_key="parse",
                project_id=None,
                agent_id="score_agent",
                skill_name="parse_score",
            )
        )
        assert len(captured) == 1
        assert captured[0]["skill_name"] == "parse_score"
        assert captured[0]["agent_id"] == "score_agent"
        assert captured[0]["ok"] is True

    def test_failure_entry_carries_attribution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """失败路径（acompletion 抛异常）同样透传 —— 0 token ≠ 没调用."""
        fired: list[dict[str, Any]] = []

        async def boom(**_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr("litellm.acompletion", boom)
        # 同上：patch caller 模块全局名（from-import 绑定）
        import app.services.llm.caller as caller_mod

        monkeypatch.setattr(caller_mod, "fire_usage_log", lambda entry: fired.append(entry))
        from app.services.llm.caller import call_and_log

        with pytest.raises(RuntimeError):
            asyncio.run(
                call_and_log(
                    "schema",
                    "m",
                    {"model": "m", "messages": []},
                    10,
                    stage_key="parse",
                    project_id=None,
                    agent_id="a",
                    skill_name="s",
                )
            )
        assert len(fired) == 1
        assert fired[0]["skill_name"] == "s"
        assert fired[0]["ok"] is False


# ── 3/4. llm_service 四入口 + chat_with_tools 两出口 ──


class _Capture:
    """捕获 _call_and_log 调用（kind + skill_name），返回可配置响应."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(
        self, kind: str, model: str, kwargs: dict[str, Any], n: int, **kw: Any
    ) -> Any:
        self.calls.append((kind, kw.get("skill_name")))
        return self.responses.pop(0)


def _patch_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 mock 环境桩：is_mock_enabled=False + resolve_llm_target 返回固定路由."""
    from app.services.infra import settings_service

    async def fake_is_mock(_mock: bool | None = None) -> bool:
        return False

    async def fake_resolve(
        _stage_key: str | None,
    ) -> tuple[str, None, dict[str, Any], dict[str, Any]]:
        return "deepseek/deepseek-chat", None, {}, {"temperature": 0.1}

    monkeypatch.setattr(settings_service, "is_mock_enabled", fake_is_mock)
    monkeypatch.setattr(settings_service, "resolve_llm_target", fake_resolve)


def _resp(content: str, tool_calls: Any = None) -> Any:
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


class TestLlmServicePassthrough:
    """四入口 skill_name kwarg → _call_and_log（patch 服务模块全局名 _call_and_log）."""

    def test_schema_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm_env(monkeypatch)
        cap = _Capture([_resp('{"ok": 1}')])
        monkeypatch.setattr(llm_service, "_call_and_log", cap)
        asyncio.run(
            llm_service.call_llm_with_schema(
                "sys", "user", {}, mock=False, stage_key="parse", skill_name="parse_score"
            )
        )
        assert cap.calls == [("schema", "parse_score")]

    def test_text_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm_env(monkeypatch)
        cap = _Capture([_resp("hi")])
        monkeypatch.setattr(llm_service, "_call_and_log", cap)
        asyncio.run(
            llm_service.call_llm_text(
                "sys", "user", mock=False, stage_key="parse", skill_name="parse_score"
            )
        )
        assert cap.calls == [("text", "parse_score")]

    def test_stream_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm_env(monkeypatch)

        # stream 响应：async iterable，chunk 结构对齐 litellm（choices[0].delta.content）
        class _Stream:
            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    chunk = SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="chunk"))]
                    )
                    yield chunk

                return gen()

        cap = _Capture([_Stream()])
        monkeypatch.setattr(llm_service, "_call_and_log", cap)

        async def run() -> list[str]:
            return [
                chunk
                async for chunk in llm_service.call_llm_stream(
                    "sys", "user", mock=False, stage_key="parse", skill_name="parse_score"
                )
            ]

        assert asyncio.run(run()) == ["chunk"]
        assert cap.calls == [("stream", "parse_score")]


class TestChatWithToolsAttribution:
    """🔴 S5 验收锚点：两条出口都落 skill_name."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> _Capture:
        _patch_llm_env(monkeypatch)
        cap = _Capture(responses)
        monkeypatch.setattr(llm_service, "_call_and_log", cap)
        return cap

    def test_normal_convergence_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """出口 1：第 1 轮即纯文本收敛（无 tool_calls）→ tools_round1 落 skill_name."""
        cap = self._run(monkeypatch, [_resp("收敛文本")])

        async def _exec(_name: str, _args: dict[str, Any]) -> str:
            return ""

        text, calls = asyncio.run(
            llm_service.chat_with_tools(
                "sys", "user", [], _exec, mock=False, stage_key="parse", skill_name="parse_score"
            )
        )
        assert text == "收敛文本"
        assert calls == []
        # 恰一次调用且带归因
        assert cap.calls == [("tools_round1", "parse_score")]

    def test_rounds_exhausted_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """出口 2：轮数耗尽 → tools_final 强收敛也落同一 skill_name."""
        tool_call = SimpleNamespace(id="c1", function=SimpleNamespace(name="t1", arguments="{}"))
        cap = self._run(
            monkeypatch,
            [_resp("第1轮", [tool_call]), _resp("第2轮", [tool_call]), _resp("最终收敛")],
        )

        async def _exec(_name: str, _args: dict[str, Any]) -> str:
            return "工具结果"

        max_rounds = 2
        text, calls = asyncio.run(
            llm_service.chat_with_tools(
                "sys",
                "user",
                [],
                _exec,
                max_rounds=max_rounds,
                mock=False,
                stage_key="parse",
                skill_name="parse_score",
            )
        )
        assert text == "最终收敛"
        assert len(calls) == 2
        kinds = [k for k, _s in cap.calls]
        assert kinds == ["tools_round1", "tools_round2", "tools_final"]
        assert all(s == "parse_score" for _k, s in cap.calls), "三条调用全部落 skill_name"


# ────────────────────────── 5. load_agent_skill_prompt 返回 skill 名 ──────────────────────────


class TestLoadAgentSkillPrompt:
    def test_hit_returns_skill_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """命中 skill 契约 → 三元组带 contract.name."""
        import app.services.document.parsing.prompts as prompts

        contract = SimpleNamespace(name="parse_score")

        async def fake_resolve(
            _aid: str, _stage: str, _ctx: dict[str, Any], *, db: Any = None
        ) -> Any:
            return ("sys", "user", contract)

        monkeypatch.setattr("app.services.skills.consume.resolve_agent_skill_prompt", fake_resolve)
        got = asyncio.run(prompts.load_agent_skill_prompt("score_agent", "parse", {}))
        assert got == ("sys", "user", "parse_score")

    def test_yaml_fallback_returns_none_skill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未命中（None）→ 返回 None（dispatch 据此把 skill_name 记 None）."""
        import app.services.document.parsing.prompts as prompts

        async def fake_resolve(
            _aid: str, _stage: str, _ctx: dict[str, Any], *, db: Any = None
        ) -> None:
            return None

        monkeypatch.setattr("app.services.skills.consume.resolve_agent_skill_prompt", fake_resolve)
        assert asyncio.run(prompts.load_agent_skill_prompt("score_agent", "parse", {})) is None

    def test_exception_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """契约解析异常 → 不上抛，返回 None（单 Agent 失败不阻断的降级契约）."""
        import app.services.document.parsing.prompts as prompts

        async def boom(_aid: str, _stage: str, _ctx: dict[str, Any], *, db: Any = None) -> Any:
            raise RuntimeError("x")

        monkeypatch.setattr("app.services.skills.consume.resolve_agent_skill_prompt", boom)
        assert asyncio.run(prompts.load_agent_skill_prompt("score_agent", "parse", {})) is None


# ────────────────────────── 6/7. skill_profiles 聚合 + 端点 ──────────────────────────


class _FakeRows:
    """execute() 返回预设行的最小 AsyncSession 替身（纯 SELECT 无 commit）."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(all=lambda: self._rows)


def _row(skill: str | None, calls: int, ok: int, fb: int, tokens: int, lat: float) -> Any:
    return SimpleNamespace(
        skill_name=skill,
        calls=calls,
        ok_calls=ok,
        fallback_count=fb,
        total_tokens=tokens,
        avg_latency_ms=lat,
    )


class TestSkillProfiles:
    def test_aggregates_with_failed_calls(self) -> None:
        """failed_calls = calls - ok_calls（0 token ≠ 没调用的判据落面）。"""
        from app.services.infra import usage_service

        db = _FakeRows([_row("parse_score", 10, 7, 1, 5000, 200.0)])
        items = asyncio.run(usage_service.skill_profiles(db, None, 7))
        assert len(items) == 1
        item = items[0]
        assert item["skill_name"] == "parse_score"
        assert item["calls"] == 10
        assert item["ok_calls"] == 7
        assert item["failed_calls"] == 3
        assert item["fallback_calls"] == 1
        assert item["success_rate"] == 0.7
        assert item["total_tokens"] == 5000
        assert item["avg_latency_ms"] == 200.0

    def test_null_skill_grouped_as_unknown(self) -> None:
        """迁移前历史行 skill_name 为 NULL → 归 "unknown"（不丢数据）."""
        from app.services.infra import usage_service

        db = _FakeRows([_row(None, 4, 4, 0, 100, 50.0)])
        items = asyncio.run(usage_service.skill_profiles(db, None, 7))
        assert items[0]["skill_name"] == "unknown"
        assert items[0]["failed_calls"] == 0

    def test_empty_window(self) -> None:
        from app.services.infra import usage_service

        db = _FakeRows([])
        assert asyncio.run(usage_service.skill_profiles(db, None, 7)) == []


class TestSkillProfilesApi:
    def test_endpoint_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GET /usage/skill-profiles：仅登录可读，items+days 结构."""
        from fastapi.testclient import TestClient

        from app.core.database import get_db
        from app.core.deps import get_current_user_id
        from app.main import app

        async def fake_profiles(_db: Any, _pid: Any, _days: int) -> list[dict[str, Any]]:
            return [{"skill_name": "parse_score", "calls": 1}]

        from app.services.infra import usage_service

        monkeypatch.setattr(usage_service, "skill_profiles", fake_profiles)

        class _Session:
            async def commit(self) -> None: ...

        app.dependency_overrides[get_db] = lambda: _Session()
        app.dependency_overrides[get_current_user_id] = lambda: (
            "00000000-0000-0000-0000-000000000001"
        )
        try:
            client = TestClient(app)
            r = client.get("/api/v1/usage/skill-profiles?days=7")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["code"] == 0
            assert body["data"]["days"] == 7
            assert body["data"]["items"][0]["skill_name"] == "parse_score"
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user_id, None)
