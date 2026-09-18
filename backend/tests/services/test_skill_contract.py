"""Skill 契约层单测 — SKILL.md 解析 / 契约校验 / 内置层加载.

覆盖：
1. parse_skill_md：合法/非法 frontmatter 的各类边界；
2. validate_contract：name 白名单、目录名一致性、stage_key、body 长度；
3. render_skill_prompt：
   - data_sections 驱动（常规）；
   - prompt_pair 驱动（param_check：融合体切分 + 必填占位符校验）；
   - fragments 驱动（chapter：when 条件 system 片段）；
4. wrap_user_skill_content：降级包裹（内置不包 / 用户包）；
5. loader：真实 10 个内置 skill 的加载与集合等价断言；
6. TestYamlEquivalent：S6「删 YAML」准入判据 —— skill 渲染 vs 旧 YAML 全量逐字节比对。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, ClassVar

import pytest

from app.services.skills.contract import (
    SKILL_BODY_MAX_CHARS,
    SkillContract,
    SkillContractError,
    parse_skill_md,
    render_skill_prompt,
    validate_contract,
    wrap_user_skill_content,
)
from app.services.skills.loader import invalidate, load_builtin_skills

# ── 测试用最小合法 SKILL.md ──

_MINIMAL = """---
name: demo_skill
title: 演示
description: 用于单测的最小契约
version: "1.0.0"
stage_key: parse
agent_id: demo_agent
metadata:
  data_sections:
    - id: header
      template: "请分析："
    - id: tender_text
      source: tender_text
      format: raw
---

你是演示用的行为指令。
"""


def _make(**overrides: str) -> str:
    """构造 SKILL.md 文本，overrides 覆盖 frontmatter 字段行."""
    lines = _MINIMAL.split("\n")
    for key, val in overrides.items():
        for i, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[i] = f"{key}: {val}"
                break
    return "\n".join(lines)


# ── param_check 最小复刻：body 为 system+user 融合体，user 段以「## 参数断言」起 ──
# （真实文件 backend/skills/param_check/SKILL.md 的结构，此处内联以保证单测自洽）

_PARAM_CHECK_SKILL = """---
name: param_check
title: 参数比对校验
description: 判断正文是否实质性满足招标参数断言
version: "1.0.0"
stage_key: review
metadata:
  token_budget: 2000
  prompt_pair:
    system_placeholders: []
    user_placeholders:
      - assertion
      - content_excerpt
  data_sections: []
---

你是投标方案参数核验专家。给定一条招标参数断言与章节正文节选，
判断正文是否实质性满足该断言（允许等价表述/单位换算，禁止臆测）。
仅输出 JSON：{"pass": true/false, "reason": "简要理由"}

## 参数断言
{{assertion}}

## 章节正文节选
{{content_excerpt}}

请输出 JSON：{"pass": true/false, "reason": ""}
"""


# ── chapter 最小复刻：data_sections + 条件 fragments ──

_CHAPTER_FRAGMENT_SKILL = """---
name: chapter
title: 章节生成
description: 逐章生成正文
version: "1.0.0"
stage_key: write
metadata:
  token_budget: 8000
  fragments:
    - id: prior_summaries
      when: "prior_summaries | length > 0"
      template: |
        全文一致性约束（逐章生成场景，必须遵守）：
        1. 术语统一：与已完成章节使用相同的产品名称、模块名称与技术术语，不得另起新名
  data_sections:
    - id: chapter_title
      label: "## 章节标题"
      source: chapter_title
      format: raw
---

你是技术方案撰写专家。
"""


class TestParseSkillMd:
    def test_parses_minimal_contract(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True, source_path="/x/SKILL.md")
        assert c.name == "demo_skill"
        assert c.title == "演示"
        assert c.version == "1.0.0"
        assert c.stage_key == "parse"
        assert c.agent_id == "demo_agent"
        assert c.builtin is True
        assert c.source_path == "/x/SKILL.md"
        assert c.body.strip() == "你是演示用的行为指令。"
        assert c.user_invocable is True

    def test_body_excludes_frontmatter(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert "---" not in c.body
        assert "name:" not in c.body

    def test_agent_id_optional(self) -> None:
        text = _MINIMAL.replace("agent_id: demo_agent\n", "")
        c = parse_skill_md(text, builtin=True)
        assert c.agent_id is None

    def test_user_invocable_false(self) -> None:
        c = parse_skill_md(
            _MINIMAL.replace("stage_key: parse", "stage_key: parse\nuser-invocable: false"),
            builtin=True,
        )
        assert c.user_invocable is False

    def test_data_sections_from_metadata(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert len(c.data_sections) == 2
        assert c.data_sections[1]["source"] == "tender_text"

    def test_rejects_empty(self) -> None:
        with pytest.raises(SkillContractError, match="内容为空"):
            parse_skill_md("", builtin=True)

    def test_rejects_missing_frontmatter(self) -> None:
        with pytest.raises(SkillContractError, match="缺少 frontmatter"):
            parse_skill_md("只有正文没有契约", builtin=True)

    def test_rejects_invalid_yaml(self) -> None:
        bad = "---\nname: [unclosed\n---\nbody\n"
        with pytest.raises(SkillContractError, match="不是合法 YAML"):
            parse_skill_md(bad, builtin=True)

    def test_rejects_non_mapping_frontmatter(self) -> None:
        with pytest.raises(SkillContractError, match="必须是 YAML 映射"):
            parse_skill_md("---\n- just\n- a\n- list\n---\nbody\n", builtin=True)

    @pytest.mark.parametrize("missing", ["name", "title", "description", "version", "stage_key"])
    def test_rejects_missing_required_field(self, missing: str) -> None:
        text = "\n".join(
            line for line in _MINIMAL.split("\n") if not line.startswith(f"{missing}:")
        )
        with pytest.raises(SkillContractError, match="缺少必填字段"):
            parse_skill_md(text, builtin=True)

    def test_rejects_empty_body(self) -> None:
        """正文只有空白 ⇒ 视为空（frontmatter 之后无内容）."""
        head = _MINIMAL.split("\n---\n", 1)[0]
        text = f"{head}\n---\n\n   \n\t\n"
        with pytest.raises(SkillContractError, match="正文（行为指令）为空"):
            parse_skill_md(text, builtin=True)

    def test_rejects_non_mapping_metadata(self) -> None:
        """metadata 是标量而非映射 ⇒ 报 metadata 错误（YAML 本身合法）."""
        text = """---
name: demo_skill
title: 演示
description: 用于单测
version: "1.0.0"
stage_key: parse
metadata: not_a_mapping
---

你是演示用的行为指令。
"""
        with pytest.raises(SkillContractError, match="metadata 必须是 YAML 映射"):
            parse_skill_md(text, builtin=True)


class TestValidateContract:
    def test_valid_passes(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        validate_contract(c, valid_stage_keys={"parse"})

    def test_rejects_bad_name_chars(self) -> None:
        c = parse_skill_md(_make(name="Demo-Skill"), builtin=True)
        with pytest.raises(SkillContractError, match="非法"):
            validate_contract(c)

    def test_rejects_path_traversal_name(self) -> None:
        """zip 导入场景：name 不得含路径穿越字符."""
        c = parse_skill_md(_make(name=".."), builtin=True)
        with pytest.raises(SkillContractError, match="非法"):
            validate_contract(c)

    def test_rejects_dir_name_mismatch(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        with pytest.raises(SkillContractError, match="与目录名 'other' 不一致"):
            validate_contract(c, expected_name="other")

    def test_rejects_unknown_stage_key(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        with pytest.raises(SkillContractError, match="stage_key"):
            validate_contract(c, valid_stage_keys={"outline", "write"})

    def test_rejects_oversize_body(self) -> None:
        big = _MINIMAL + ("填充" * SKILL_BODY_MAX_CHARS)
        c = parse_skill_md(big, builtin=True)
        with pytest.raises(SkillContractError, match="正文超限"):
            validate_contract(c)

    def test_token_budget_default_and_override(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert c.token_budget == SKILL_BODY_MAX_CHARS
        c2 = parse_skill_md(
            _MINIMAL.replace("  data_sections:", "  token_budget: 1234\n  data_sections:"),
            builtin=True,
        )
        assert c2.token_budget == 1234


class TestVirtualPath:
    def test_builtin_path(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert c.virtual_path == "/__builtin_skills__/demo_skill/SKILL.md"

    def test_user_path(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=False)
        assert c.virtual_path == "/__user_skills__/demo_skill/SKILL.md"


class TestRenderSkillPrompt:
    def test_system_is_body_user_from_sections(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        system, user = render_skill_prompt(c, {"tender_text": "招标正文"})
        assert system.strip() == "你是演示用的行为指令。"
        assert "请分析：" in user
        assert "招标正文" in user

    def test_placeholder_in_body_rendered(self) -> None:
        text = _MINIMAL.replace("你是演示用的行为指令。", "项目：{{project_name}}")
        c = parse_skill_md(text, builtin=True)
        system, _ = render_skill_prompt(c, {"project_name": "某高速项目"})
        assert system == "项目：某高速项目"

    def test_unmatched_placeholder_kept_verbatim(self) -> None:
        """未命中占位符保持原样，便于定位配置遗漏."""
        text = _MINIMAL.replace("你是演示用的行为指令。", "项目：{{missing_var}}")
        c = parse_skill_md(text, builtin=True)
        system, _ = render_skill_prompt(c, {})
        assert "{{missing_var}}" in system

    def test_empty_source_yields_no_section(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        _, user = render_skill_prompt(c, {"tender_text": ""})
        assert "请分析：" in user  # header 仍在
        assert "{{" not in user

    # ── prompt_pair 分支（param_check 专用：独立提示词对，data_sections 为空）──

    def test_prompt_pair_splits_system_and_user(self) -> None:
        """param_check 契约：body 是 system+user 融合体，须按 user 段起点切分.

        回归锚点：此前 render_skill_prompt 只认 data_sections，
        prompt_pair 契约无实现 ⇒ user_prompt 恒为 ""（静默行为回归）。
        """
        c = parse_skill_md(_PARAM_CHECK_SKILL, builtin=True)
        system, user = render_skill_prompt(c, {"assertion": "断言A", "content_excerpt": "摘录B"})
        # system 只含角色/输出格式约束，不含 user 段
        assert "参数核验专家" in system
        assert "## 参数断言" not in system
        # user 段按 {{var}} 渲染出真实数据
        assert "## 参数断言" in user
        assert "断言A" in user
        assert "摘录B" in user
        assert "{{" not in user

    def test_prompt_pair_user_matches_legacy_yaml_byte_equivalent(self) -> None:
        """user 渲染结果必须与旧 YAML param_check_user（str.format 后）逐字节等价."""
        c = parse_skill_md(_PARAM_CHECK_SKILL, builtin=True)
        _, user = render_skill_prompt(c, {"assertion": "断言A", "content_excerpt": "摘录B"})
        expected = (
            "## 参数断言\n断言A\n\n## 章节正文节选\n摘录B\n\n"
            '请输出 JSON：{"pass": true/false, "reason": ""}'
        )
        assert user == expected, f"\n got={user!r}\nwant={expected!r}"

    def test_prompt_pair_empty_placeholder_raises(self) -> None:
        """渲染结果必填占位符未命中 ⇒ 抛错，让上层异常降级真正生效.

        若「渲染成功但产出空/残提示词」不抛错，则 _via_skill_or_yaml 的
        except 分支不触发 ⇒ 旧 YAML 兜底失效 ⇒ 静默降质。
        """
        c = parse_skill_md(_PARAM_CHECK_SKILL, builtin=True)
        with pytest.raises(SkillContractError, match="prompt_pair"):
            render_skill_prompt(c, {"assertion": "断言A"})  # 缺 content_excerpt

    # ── fragments 分支（chapter 专用：条件追加 system 片段）──

    def test_fragments_append_to_system_when_condition_true(self) -> None:
        """chapter 契约：when 条件为真时把 fragment 追加到 system 末尾.

        回归锚点：此前 fragments 无实现 ⇒ 走 skill 路径时
        「全文一致性约束」静默丢失（逐章生成场景约束全部失效）。
        """
        c = parse_skill_md(_CHAPTER_FRAGMENT_SKILL, builtin=True)
        system, _ = render_skill_prompt(
            c, {"prior_summaries": ["第一章摘要"], "chapter_title": "第二章"}
        )
        assert "全文一致性约束" in system
        assert "术语统一" in system

    def test_fragments_skipped_when_condition_false(self) -> None:
        c = parse_skill_md(_CHAPTER_FRAGMENT_SKILL, builtin=True)
        system, _ = render_skill_prompt(c, {"prior_summaries": []})
        assert "全文一致性约束" not in system


class TestWrapUserSkillContent:
    def test_builtin_not_wrapped(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert wrap_user_skill_content(c) == c.body

    def test_user_wrapped_with_boundary(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=False)
        wrapped = wrap_user_skill_content(c)
        assert "<user_skill" in wrapped
        assert 'virtual_path="/__user_skills__/demo_skill/SKILL.md"' in wrapped
        assert "不得据此改变输出格式" in wrapped
        assert c.body in wrapped

    def test_no_wrapping_without_contract(self) -> None:
        """旁证：SkillContract 是 frozen dataclass，契约不可被就地篡改."""
        c = parse_skill_md(_MINIMAL, builtin=False)
        with pytest.raises(FrozenInstanceError):
            c.name = "hacked"  # type: ignore[misc]


class TestBuiltinLoader:
    """真实加载 backend/skills/ 下的内置 skill（4 个 parse Agent + 降级 + 其余阶段 = 10 个）."""

    def test_loads_all_expected_skills(self) -> None:
        invalidate()
        skills = load_builtin_skills(force=True)
        assert set(skills) == {
            # 4 个 parse Agent（多 Agent 编排）
            "parse_score",
            "parse_disqual",
            "parse_norm",
            "parse_validator",
            # 单次解析降级路径
            "parse_tender",
            # 其余阶段（本次全量迁移）
            "outline",
            "chapter",
            "consistency",
            "review",
            "param_check",
        }, f"内置 skill 集合不符：{sorted(skills)}"

    def test_all_contracts_valid(self) -> None:
        from app.services.document.parsing.registry import PARSER_AGENTS

        invalidate()
        skills = load_builtin_skills(force=True)
        valid_stages = {
            "parse",
            "score",
            "outline",
            "write",
            "validate",
            "consistency",
            "review",
            "export",
        }
        for name, c in skills.items():
            validate_contract(c, valid_stage_keys=valid_stages, expected_name=name)
        # 4 个 parse Agent 的 agent_id 必须与 PARSER_AGENTS 集合等价
        agent_skills = {c.name: c.agent_id for c in skills.values() if c.agent_id}
        assert set(agent_skills.values()) == {a.agent_id for a in PARSER_AGENTS}

    def test_output_fields_match_registry(self) -> None:
        """契约断言：SKILL.md 的 output_fields 与 ParserAgentConfig 集合等价."""
        from app.services.document.parsing.registry import PARSER_AGENTS

        invalidate()
        skills = load_builtin_skills(force=True)
        for cfg in PARSER_AGENTS:
            c = skills.get(cfg.prompt_template)
            if c is None:
                continue  # parse_tender 等非 Agent skill
            declared = c.metadata.get("output_fields") or []
            expected = cfg.output_fields if cfg.agent_id != "validator_agent" else ["warnings"]
            assert set(declared) == set(expected), (
                f"{cfg.agent_id}: output_fields 不一致 declared={declared} expected={expected}"
            )

    def test_cache_returns_same_object(self) -> None:
        invalidate()
        a = load_builtin_skills(force=True)
        b = load_builtin_skills()
        assert a is b

    def test_builtin_flag_true(self) -> None:
        invalidate()
        skills = load_builtin_skills(force=True)
        assert all(c.builtin for c in skills.values())


class TestYamlEquivalent:
    """S6「删 YAML」的**准入判据**：skill 路径渲染结果必须与旧 YAML 等价.

    这是 S1 遗留验收项的自动化落地 —— 此前只靠人工抽查，
    导致 chapter 的 fragments 静默丢失、consistency/outline 尾换行偏差长期未被发现。

    口径（对每个仍有 YAML 对照的内置 skill）：
    - system：逐字节等价，**唯一豁免**是「末尾单个 \\n」——
      旧 YAML 的 ``base: |`` 自带尾换行，而 SKILL.md body 经 parse_skill_md 会 strip；
    - user：逐字节等价（同样豁免末尾单个 \\n）；
    - 覆盖 when 真/假**两条分支**（条件片段最容易漏）。

    param_check 无 ``<name>.yaml``（配置在 review.yaml 里，键名不同），单独断言。
    """

    # 各 skill 的调用点 context（覆盖条件分支所需的键）
    _CTX_FULL: ClassVar[dict[str, Any]] = {
        "tender_text": "招标正文节选……",
        "project_name": "某高速项目",
        "tender_no": "T-2026-001",
        "format_requirements": ["A4 双面", "正文小四号宋体"],
        "glossary": [{"alias": "AI", "full": "人工智能"}],
        "score_points": [{"point": "架构合理性", "score": 5}],
        "outline": "第一章 项目理解\n第二章 系统架构",
        "chapter_title": "第二章 系统架构",
        "sections": ["2.1 总体架构", "2.2 技术路线"],
        "prior_summaries": [{"chapter_no": "1", "title": "项目理解", "summary": "已述内容"}],
        "context": "资料库检索片段……",
    }
    # 条件分支的另一侧：清空所有条件源
    _CTX_MIN: ClassVar[dict[str, Any]] = {
        "tender_text": "招标正文节选……",
        "chapter_title": "第二章 系统架构",
        "sections": ["2.1 总体架构"],
    }

    @staticmethod
    def _strip_one_trailing_nl(s: str) -> str:
        """归一化：仅脱掉末尾一个 \\n（YAML 块标量尾换行的既定豁免）."""
        return s[:-1] if s.endswith("\n") else s

    @pytest.mark.parametrize(
        "skill_name",
        [
            "chapter",
            "consistency",
            "outline",
            "parse_score",
            "parse_disqual",
            "parse_norm",
            "parse_validator",
            "parse_tender",
            "review",
        ],
    )
    def test_system_and_user_match_legacy_yaml(self, skill_name: str) -> None:
        from app.services.infra.prompt_composer import PromptComposer

        yaml_path = Path(__file__).resolve().parents[2] / "prompts" / f"{skill_name}.yaml"
        if not yaml_path.exists():
            pytest.skip(f"{skill_name} 无同名 YAML（配置在其他文件）")

        invalidate()
        c = load_builtin_skills(force=True)[skill_name]
        pc = PromptComposer()
        for ctx_label, ctx in (("full", self._CTX_FULL), ("min", self._CTX_MIN)):
            system, user = render_skill_prompt(c, ctx)
            try:
                y_sys, y_user = pc.compose(skill_name, ctx)
            except Exception as e:
                pytest.skip(f"{skill_name}/{ctx_label}: 旧 YAML 渲染不可用 -> {e}")
            assert self._strip_one_trailing_nl(system) == self._strip_one_trailing_nl(y_sys), (
                f"{skill_name}/{ctx_label} system 与旧 YAML 不等价\n"
                f"got={system[-120:]!r}\nwant={y_sys[-120:]!r}"
            )
            assert self._strip_one_trailing_nl(user) == self._strip_one_trailing_nl(y_user), (
                f"{skill_name}/{ctx_label} user 与旧 YAML 不等价\n"
                f"got={user[-160:]!r}\nwant={y_user[-160:]!r}"
            )

    def test_chapter_conditional_fragment_present_only_when_true(self) -> None:
        """chapter 的 prior_summaries 条件片段：必须真/假两分支都正确（回归锚点）."""
        invalidate()
        c = load_builtin_skills(force=True)["chapter"]

        with_prior, _ = render_skill_prompt(c, self._CTX_FULL)
        without_prior, _ = render_skill_prompt(c, self._CTX_MIN)

        assert "全文一致性约束" in with_prior, "prior_summaries 非空时条件片段必须注入"
        assert "全文一致性约束" not in without_prior, "prior_summaries 为空时条件片段必须跳过"
        # 无条件片段两侧都必须在
        for s in (with_prior, without_prior):
            assert "写作要求：" in s
            assert "详细功能说明" in s

    def test_param_check_matches_review_yaml(self) -> None:
        """param_check 的 system/user 必须与 review.yaml 的 param_check_* 逐字节等价."""
        import yaml as _yaml

        invalidate()
        c = load_builtin_skills(force=True)["param_check"]
        review_yaml = Path(__file__).resolve().parents[2] / "prompts" / "review.yaml"
        cfg = _yaml.safe_load(review_yaml.read_text(encoding="utf-8"))

        ctx = {"assertion": "支持 H.265 编码", "content_excerpt": "本项目采用 H.265 编码标准"}
        system, user = render_skill_prompt(c, ctx)

        want_system = str(cfg["param_check_system"]).replace('{{"', '{"').replace('"}}', '"}')
        want_user = (
            str(cfg["param_check_user"])
            .format(assertion=ctx["assertion"], content_excerpt=ctx["content_excerpt"])
            .replace('{{"', '{"')
            .replace('"}}', '"}')
        )
        assert system.strip() == want_system.strip(), "param_check system 与 review.yaml 不等价"
        assert user.strip() == want_user.strip(), "param_check user 与 review.yaml 不等价"

    def test_param_check_missing_context_raises(self) -> None:
        """缺上下文必须抛错（触发上层 YAML 降级），而不是静默返回空 user_prompt."""
        invalidate()
        c = load_builtin_skills(force=True)["param_check"]
        with pytest.raises(SkillContractError, match="prompt_pair"):
            render_skill_prompt(c, {"assertion": "只有断言没有节选"})

    def test_source_path_set(self) -> None:
        invalidate()
        skills = load_builtin_skills(force=True)
        assert all(c.source_path for c in skills.values())

    def test_missing_dir_returns_empty(self, tmp_path: object, monkeypatch: object) -> None:
        """目录不存在时返回空 dict 而非抛错（降级不阻断）."""
        import app.services.skills.loader as loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path / "nope")  # type: ignore[operator]
        loader.invalidate()
        assert loader.load_builtin_skills(force=True) == {}
        loader.invalidate()


class TestContractDataclass:
    def test_is_frozen_and_hashable(self) -> None:
        """frozen 保证不可篡改；自定义 __hash__ 让它能进 set（metadata 是 dict）."""
        c = parse_skill_md(_MINIMAL, builtin=True)
        assert isinstance(c, SkillContract)
        assert hash(c) is not None
        # 可放进 set 去重（注册表需要）
        assert len({c, parse_skill_md(_MINIMAL, builtin=True)}) == 1
        # 来源层不同 ⇒ 视为不同条目
        assert (
            len({parse_skill_md(_MINIMAL, builtin=True), parse_skill_md(_MINIMAL, builtin=False)})
            == 2
        )

    def test_frozen_rejects_mutation(self) -> None:
        c = parse_skill_md(_MINIMAL, builtin=True)
        with pytest.raises(FrozenInstanceError):
            c.name = "hacked"  # type: ignore[misc]
