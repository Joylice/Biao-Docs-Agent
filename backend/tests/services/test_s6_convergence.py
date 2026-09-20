"""S6 收敛测试 —— 删 per-agent YAML 回退层（双轨期结束）.

删除面（改造计划 §七）：
1. prompts.load_parser_agent_prompt（per-agent YAML + parse.yaml 二级回退，含 BizError/5009 分支）；
2. dispatch._run_single_agent 的 YAML 回退分支（skill 未命中 → 直接兜底旧 parse.yaml）；
3. backend/prompts/ 下 4 份 parse_*.yaml（真源已迁 backend/skills/<name>/SKILL.md）。

保留：parse.yaml（兜底 + 单次降级路径）+ outline/chapter/review/consistency（未迁移阶段）。

守卫设计：被删对象用「不存在」断言机械防回退；兜底行为用 monkeypatch 隔离
（patch 位置遵守铁律⑩：dispatch 模块级 import 打调用方全局名，函数内延迟 import 打真模块）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.services.document.parsing import dispatch as dispatch_mod
from app.services.document.parsing import prompts as prompts_mod
from app.services.document.parsing.registry import get_agent_config

BACKEND = Path(__file__).resolve().parents[2]

REMOVED_YAML = [
    "parse_score.yaml",
    "parse_disqual.yaml",
    "parse_norm.yaml",
    "parse_validator.yaml",
]
KEPT_YAML = ["parse.yaml", "outline.yaml", "chapter.yaml", "review.yaml", "consistency.yaml"]


class TestRemovedSurface:
    """删除面守卫：被删对象不得回来、保留对象不得丢。"""

    def test_prompts_no_longer_exports_legacy_loader(self) -> None:
        """load_parser_agent_prompt 已删，prompts 模块不得再导出（防回退）。"""
        assert not hasattr(prompts_mod, "load_parser_agent_prompt")

    def test_removed_yaml_files_gone(self) -> None:
        """per-agent 四 YAML 已删（真源 = skills/<name>/SKILL.md）。"""
        for name in REMOVED_YAML:
            assert not (BACKEND / "prompts" / name).exists(), f"{name} 应已删除（S6）"

    def test_kept_yaml_files_still_present(self) -> None:
        """parse.yaml 与未迁移阶段的 YAML 必须保留。"""
        for name in KEPT_YAML:
            assert (BACKEND / "prompts" / name).exists(), f"{name} 必须保留（未迁移阶段）"


class TestSkillMissFallback:
    """skill 未命中 → 直接兜底旧 parse.yaml（load_parse_prompt），不再经过 per-agent YAML。"""

    @staticmethod
    def _patch_env(
        monkeypatch: pytest.MonkeyPatch,
        parse_yaml_stub: Any,
        schema_stub: Any,
    ) -> None:
        """隔离 _run_single_agent 的全部外部依赖（零 LLM / 零 DB）。"""

        async def fake_skill(_aid: str, _stage: str, _ctx: dict[str, Any]) -> None:
            return None  # skill 契约未命中

        monkeypatch.setattr(dispatch_mod, "load_agent_skill_prompt", fake_skill)
        # parse.yaml 兜底：dispatch 函数内延迟 import → patch 真模块（铁律⑩）
        monkeypatch.setattr("app.services.infra.prompt_loader.load_parse_prompt", parse_yaml_stub)
        # 内置工具/外部工具全空 → 走单段 call_llm_with_schema 分支
        monkeypatch.setattr(dispatch_mod, "get_allowed_tools_for_agent", lambda *_a, **_k: [])

        async def fake_ext_defs(_stage: str, _pid: str | None) -> list[Any]:
            return []

        monkeypatch.setattr("app.services.infra.tools.registry.get_definitions", fake_ext_defs)
        # LLM 桩：延迟 import → patch 真模块 llm_service
        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", schema_stub)

    def test_miss_falls_directly_to_parse_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未命中 → parse.yaml 兜底提示词进入 LLM 调用；per-agent YAML 层不参与。"""
        yaml_calls: list[str] = []

        def fake_load_parse_prompt(text: str) -> tuple[str, str]:
            yaml_calls.append(text)
            return ("SYS-PARSE-YAML", "USER-PARSE-YAML")

        llm_calls: list[dict[str, Any]] = []

        async def fake_schema(**kw: Any) -> dict[str, Any]:
            llm_calls.append(kw)
            return {"score_points": [], "project_name": "P", "tender_no": "T-1"}

        self._patch_env(monkeypatch, fake_load_parse_prompt, fake_schema)

        cfg = get_agent_config("score_agent")
        assert cfg is not None
        result = asyncio.run(dispatch_mod._run_single_agent(cfg, "招标窗口文本", None, False, None))

        assert result.success is True
        assert len(yaml_calls) == 1, "parse.yaml 兜底被调用一次"
        assert llm_calls, "LLM 被调用"
        assert llm_calls[0]["system_prompt"] == "SYS-PARSE-YAML"
        assert llm_calls[0]["user_prompt"] == "USER-PARSE-YAML"
        # 未命中 ⇒ skill_name 为 None（归因不落具体准则）
        assert llm_calls[0]["skill_name"] is None

    def test_fallback_failure_returns_failed_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parse.yaml 兜底自身失败 → 「单 Agent 失败不阻断」，返回失败 AgentResult 而非上抛。

        断言收紧：LLM 桩只记录不抛 —— 兜底失败时 LLM 必须一次都不被调
        （若走旧 per-agent YAML 链则提示词加载成功 → LLM 被调 → 断言红）。
        """
        llm_calls: list[dict[str, Any]] = []

        def boom(_text: str) -> tuple[str, str]:
            raise RuntimeError("parse.yaml 损坏")

        async def fake_schema(**kw: Any) -> dict[str, Any]:
            llm_calls.append(kw)
            return {"disqualification_clauses": []}

        self._patch_env(monkeypatch, boom, fake_schema)

        cfg = get_agent_config("disqual_agent")
        assert cfg is not None
        result = asyncio.run(dispatch_mod._run_single_agent(cfg, "招标窗口文本", None, False, None))

        assert result.success is False
        assert result.data == {}
        assert llm_calls == [], "兜底加载失败后不应调用 LLM"
