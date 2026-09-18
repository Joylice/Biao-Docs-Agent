"""提示词模板加载器（DSL 版）.

内部改调 PromptComposer 引擎，对外接口签名不变（向后兼容）。
7 个既有 load_*_prompt() 函数保持原有参数列表和返回值。
新增 load_parser_agent_prompt() 用于解析多智能体（T1.2）。
"""

from typing import Any

from app.services.infra.prompt_composer import PromptComposer

_composer = PromptComposer()


def _load_template(name: str) -> dict[str, Any]:
    """加载指定名称的 YAML 模板（向后兼容，内部委托给 PromptComposer）."""
    return _composer._load_template(name)


def load_parse_prompt(tender_text: str) -> tuple[str, str]:
    """加载招标解析提示词模板."""
    return _composer.compose("parse", {"tender_text": tender_text})


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


def load_outline_prompt(
    score_points: list[dict[str, Any]],
    project_name: str = "",
    tender_no: str = "",
    industry: str = "",
) -> tuple[str, str]:
    """加载大纲生成提示词模板（2026-08-25：评分点为核心纲要）.

    大纲仅以评分点为核心纲要组织章节，不再注入技术需求（P3 全链路移除）。
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

    # outline 模板的 sections 使用 raw 格式，直接传字符串
    return _composer.compose(
        "outline",
        {
            "score_points": sp_text,
            "project_context": project_context,
        },
    )


def load_chapter_prompt(
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
    """
    return _composer.compose(
        "chapter",
        {
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
        },
    )


def load_review_prompt(
    chapter_summary: str,
    score_points: str,
) -> tuple[str, str]:
    """加载审阅提示词模板."""
    return _composer.compose(
        "review",
        {
            "chapter_summary": chapter_summary,
            "score_points": score_points,
        },
    )


def load_param_check_prompt(assertion: str, content_excerpt: str) -> tuple[str, str]:
    """加载参数比对校验提示词模板（阶段 E1：review.yaml param_check 段）.

    param_check 为独立提示词对（非 DSL 组装范围），保留 str.format 渲染。
    """
    config = _load_template("review")
    system_prompt = config.get("param_check_system", "")
    user_prompt_template = config.get("param_check_user", "")
    user_prompt = user_prompt_template.format(
        assertion=assertion,
        content_excerpt=content_excerpt,
    )
    return system_prompt, user_prompt


def load_consistency_prompt(full_text: str) -> tuple[str, str]:
    """加载全文一致性检查提示词模板."""
    return _composer.compose("consistency", {"full_text": full_text})


def load_parser_agent_prompt(agent_id: str, context: dict[str, Any]) -> tuple[str, str]:
    """加载解析 Agent 提示词（T1.2）.

    模板文件：prompts/parse_{agent_id}.yaml
    （score_agent → parse_score.yaml, validator_agent → parse_validator.yaml, …）

    向后兼容：P1 阶段如果 parse_{agent_id}.yaml 不存在，回退到旧 parse.yaml
    （行为等价，保证不 break 旧测试）。

    Args:
        agent_id: Agent 标识（如 "score_agent"）。
        context: 渲染上下文（含 tender_text、prior_results 等）。

    Returns:
        (system_prompt, user_prompt) 字符串。
    """
    template_name = f"parse_{agent_id}"
    try:
        return _composer.compose(template_name, context)
    except Exception:
        # P1 回退：parse_score/parse_disqual/parse_norm/parse_validator 尚未创建时
        # 用旧 parse.yaml，行为与单次 LLM 调用等价（保证 G1 行为等价判据）
        return _composer.compose("parse", context)
