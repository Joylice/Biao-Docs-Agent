"""提示词模板加载器（DSL 版）.

内部改调 PromptComposer 引擎，对外接口签名不变（向后兼容）。
7 个既有 load_*_prompt() 函数保持原有参数列表和返回值。

S3 变更（2026-09-18）：以上 7 个函数**统一改为「先查 skill 注册表，未命中回退 YAML」**。
- 新路径：`skills.consume.resolve_skill_prompt`（用户层可覆盖内置层）；
- 降级路径：原 `_composer.compose(...)`（S6 才删）。
- 回退条件：注册表未命中 / 渲染异常。**降级不阻断** —— 绝不能让「准则体系出问题」
  变成「方案编不出来」。
"""

import logging
from collections.abc import Callable
from typing import Any

from app.services.infra.prompt_composer import PromptComposer

logger = logging.getLogger(__name__)

_composer = PromptComposer()


def _load_template(name: str) -> dict[str, Any]:
    """加载指定名称的 YAML 模板（向后兼容，内部委托给 PromptComposer）."""
    return _composer._load_template(name)


def _composer_compose_param_check(assertion: str, content_excerpt: str) -> tuple[str, str]:
    """param_check 的 YAML 降级路径（原实现，保留至 S6）."""
    config = _load_template("review")
    system_prompt = config.get("param_check_system", "")
    user_prompt_template = config.get("param_check_user", "")
    user_prompt = user_prompt_template.format(
        assertion=assertion,
        content_excerpt=content_excerpt,
    )
    return system_prompt, user_prompt


async def _via_skill_or_yaml(
    skill_name: str,
    context: dict[str, Any],
    yaml_fallback: Callable[[], tuple[str, str]],
) -> tuple[str, str]:
    """统一取提示词：skill 注册表优先，未命中/异常回退 YAML.

    Args:
        skill_name: 契约名（如 "outline"）。
        context: 数据注入上下文。
        yaml_fallback: 零参可调用，返回旧 YAML 渲染结果（延迟求值，命中 skill 时不执行）。
    """
    from app.services.skills.consume import SkillNotFound, resolve_skill_prompt

    try:
        system_prompt, user_prompt, _contract = await resolve_skill_prompt(
            skill_name, context, db=None
        )
        return system_prompt, user_prompt
    except SkillNotFound:
        logger.debug("skill '%s' 未命中注册表，回退 YAML 模板", skill_name)
    except Exception:
        # 渲染异常（契约字段缺失/格式化失败）也必须降级，不能阻断生成
        logger.warning("skill '%s' 渲染失败，回退 YAML 模板", skill_name, exc_info=True)
    return yaml_fallback()


def load_parse_prompt(tender_text: str) -> tuple[str, str]:
    """加载招标解析提示词模板."""
    return _composer.compose("parse", {"tender_text": tender_text})


async def load_parse_prompt_async(tender_text: str) -> tuple[str, str]:
    """`load_parse_prompt` 的 skill 优先版（parse 阶段降级路径专用）."""
    return await _via_skill_or_yaml(
        "parse_tender",
        {"tender_text": tender_text},
        lambda: _composer.compose("parse", {"tender_text": tender_text}),
    )


def _sp_flag(sp: dict[str, Any]) -> str:
    """评分点状态标记（星号/风险）.

    2026-08-25 严格模式：进入大纲生成的评分点均为已确认（confirmed=true），
    不再标注"未确认"；星号与风险等级仍保留用于强调重点评分点。
    """
    flags: list[str] = []
    if sp.get("is_star"):
        flags.append("★")
    risk = sp.get("risk_level")
    if risk in ("high", "mid", "low"):
        flags.append(f"风险:{risk}")
    return " ".join(flags).strip()


async def load_outline_prompt(
    score_points: list[dict[str, Any]],
    project_name: str = "",
    tender_no: str = "",
    industry: str = "",
) -> tuple[str, str]:
    """加载大纲生成提示词模板（2026-08-25：评分点为核心纲要）.

    大纲仅以评分点为核心纲要组织章节，不再注入技术需求（P3 全链路移除）。
    2026-09-18（S3）：改为 async，优先取 skill 注册表的 `outline` 契约。

    注意 `sections` 在本契约里用 `format: raw`（score_points / project_context
    已是格式化好的字符串）。
    """
    # 评分点 → 章节纲要（不再分组关联技术需求）
    sp_lines: list[str] = []
    for sp in score_points:
        flag = _sp_flag(sp)
        head = (
            f"- 评分点 {sp.get('clause_no', '')} {sp.get('item', '')}（分值{sp.get('score', '?')}）"
        )
        if flag:
            head += f" [{flag}]"
        sp_lines.append(head)
        # 应对策略（解析确认页人工填写）
        strategy = sp.get("strategy")
        if strategy:
            sp_lines.append(f"  应对策略：{strategy}")
    sp_text = "\n".join(sp_lines) or "- （无评分点）"

    ctx_lines: list[str] = []
    if project_name:
        ctx_lines.append(f"- 项目名称：{project_name}")
    if tender_no:
        ctx_lines.append(f"- 招标编号：{tender_no}")
    if industry:
        ctx_lines.append(f"- 所属行业：{industry}")
    project_context = "\n".join(ctx_lines) or "- （无项目信息）"

    context: dict[str, Any] = {
        "score_points": sp_text,
        "project_context": project_context,
    }
    return await _via_skill_or_yaml(
        "outline",
        context,
        lambda: _composer.compose("outline", context),
    )


async def load_chapter_prompt(
    chapter_title: str,
    sections: list[str],
    context: str,
    score_points: str,
    prior_summaries: str = "",
    supplement_points: str = "",
    benchmark_high_risk: str = "",
    glossary: str = "",
) -> tuple[str, str]:
    """加载章节生成提示词模板.

    向后兼容：接收的是已格式化字符串参数。
    DSL 模板期望结构化数据做条件判断，这里做适配——
    非空字符串保留为 raw 格式输出，空字符串映射为不注入（when 条件为假）。
    2026-09-18（S3）：改为 async，优先取 skill 注册表的 `chapter` 契约。
    """
    ctx: dict[str, Any] = {
        "chapter_title": chapter_title,
        "sections": sections,
        "context": context,
        "score_points": score_points,
        # 非空字符串直接传入（PromptComposer 检测为字符串时走 raw 格式）
        # 空字符串映射为空列表让 when: length > 0 为假（跳过该 section）
        "prior_summaries": prior_summaries if prior_summaries else [],
        "supplement_points": supplement_points if supplement_points else [],
        "benchmark_high_risk": benchmark_high_risk if benchmark_high_risk else [],
        "glossary": glossary if glossary else [],
    }
    return await _via_skill_or_yaml(
        "chapter",
        ctx,
        lambda: _composer.compose("chapter", ctx),
    )


async def load_review_prompt(
    chapter_summary: str,
    score_points: str,
) -> tuple[str, str]:
    """加载审阅提示词模板（S3：优先取 skill 注册表的 `review` 契约）."""
    ctx: dict[str, Any] = {
        "chapter_summary": chapter_summary,
        "score_points": score_points,
    }
    return await _via_skill_or_yaml(
        "review",
        ctx,
        lambda: _composer.compose("review", ctx),
    )


async def load_param_check_prompt(assertion: str, content_excerpt: str) -> tuple[str, str]:
    """加载参数比对校验提示词模板（阶段 E1：review.yaml param_check 段）.

    param_check 为**独立提示词对**（非 DSL 组装范围），契约里用
    `metadata.prompt_pair` 表达（`user_placeholders: [assertion, content_excerpt]`）。
    S3：优先取 skill 注册表的 `param_check` 契约。
    """
    ctx: dict[str, Any] = {"assertion": assertion, "content_excerpt": content_excerpt}
    return await _via_skill_or_yaml(
        "param_check",
        ctx,
        lambda: _composer_compose_param_check(assertion, content_excerpt),
    )


async def load_consistency_prompt(full_text: str) -> tuple[str, str]:
    """加载全文一致性检查提示词模板（S3：优先取 skill 注册表的 `consistency` 契约）."""
    ctx: dict[str, Any] = {"full_text": full_text}
    return await _via_skill_or_yaml(
        "consistency",
        ctx,
        lambda: _composer.compose("consistency", ctx),
    )


# 2026-09-18 删除：load_parser_agent_prompt 曾在此重复实现（与
# app/services/document/parsing/prompts.py 逐字相同），属死代码 ——
# 全仓唯一调用方是 dispatch.py:27 `from app.services.document.parsing.prompts import
# build_agent_context, load_parser_agent_prompt`，本模块这份从未被导入过。
# 保留一份实现（parsing/prompts.py），避免「改一处漏一处」的静默分叉。
