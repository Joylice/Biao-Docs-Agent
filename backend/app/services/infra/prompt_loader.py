"""提示词模板加载器."""

from pathlib import Path

import yaml

from app.core.exceptions import BizError

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def _load_template(name: str) -> dict:
    """加载指定名称的 YAML 模板."""
    try:
        template = (_PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BizError(code=5009, message=f"提示词模板 {name}.yaml 不存在") from None
    return yaml.safe_load(template)


def load_parse_prompt(tender_text: str) -> tuple[str, str]:
    """加载招标解析提示词模板."""
    config = _load_template("parse")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "{tender_text}")
    user_prompt = user_prompt_template.format(tender_text=tender_text)
    return system_prompt, user_prompt


def _sp_flag(sp: dict) -> str:
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
    score_points: list[dict],
    tech_requirements: list[dict],
    project_name: str = "",
    tender_no: str = "",
    industry: str = "",
) -> tuple[str, str]:
    """加载大纲生成提示词模板（2026-08-25：评分点为核心纲要）.

    组装原则：以选定的评分点为核心纲要，每个评分点下挂其关联技术需求
    （tech_requirements.sp_id 匹配评分点 id），子节由关联需求推导；
    未关联任何评分点的通用需求（sp_id=None）单独列出作补充。
    """
    config = _load_template("outline")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "")

    # 评分点 → 关联需求分组（sp_id 匹配评分点 id）
    req_by_sp: dict[str, list[dict]] = {}
    general_reqs: list[dict] = []
    for tr in tech_requirements:
        if tr.get("sp_id"):
            req_by_sp.setdefault(tr["sp_id"], []).append(tr)
        else:
            general_reqs.append(tr)

    sp_lines: list[str] = []
    for sp in score_points:
        flag = _sp_flag(sp)
        head = (
            f"- 评分点 {sp.get('clause_no', '')} {sp.get('item', '')}"
            f"（分值{sp.get('score', '?')}）"
        )
        if flag:
            head += f" [{flag}]"
        sp_lines.append(head)
        # 应对策略（解析确认页人工填写）
        strategy = sp.get("strategy")
        if strategy:
            sp_lines.append(f"  应对策略：{strategy}")
        # 关联技术需求（子节推导来源）
        related = req_by_sp.get(sp.get("id", ""), [])
        if related:
            sp_lines.append("  关联技术需求：")
            for tr in related:
                sp_lines.append(
                    f"    - [{tr.get('category') or '通用'}] {tr.get('description', '')}"
                )
    sp_text = "\n".join(sp_lines) or "- （无评分点）"

    # 未关联评分点的通用需求（作补充纲要）
    tr_text = "\n".join(
        f"- [{tr.get('category', '')}] {tr.get('description', '')}" for tr in general_reqs
    )
    tr_text = tr_text or "- （无通用需求）"

    ctx_lines: list[str] = []
    if project_name:
        ctx_lines.append(f"- 项目名称：{project_name}")
    if tender_no:
        ctx_lines.append(f"- 招标编号：{tender_no}")
    if industry:
        ctx_lines.append(f"- 所属行业：{industry}")
    project_context = "\n".join(ctx_lines) or "- （无项目信息）"

    user_prompt = user_prompt_template.format(
        score_points=sp_text,
        tech_requirements=tr_text,
        project_context=project_context,
    )
    return system_prompt, user_prompt


def load_chapter_prompt(
    chapter_title: str,
    sections: list[str],
    context: str,
    score_points: str,
    tech_requirements: str,
    prior_summaries: str = "",
    supplement_points: str = "",
    benchmark_high_risk: str = "",
    glossary: str = "",
) -> tuple[str, str]:
    """加载章节生成提示词模板."""
    config = _load_template("chapter")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "")

    sections_text = "\n".join(f"- {s}" for s in sections)
    user_prompt = user_prompt_template.format(
        chapter_title=chapter_title,
        sections=sections_text,
        context=context,
        score_points=score_points,
        tech_requirements=tech_requirements,
        prior_summaries=prior_summaries,
        supplement_points=supplement_points,
        benchmark_high_risk=benchmark_high_risk or "（无）",
        glossary=glossary or "（无）",
    )
    return system_prompt, user_prompt


def load_review_prompt(
    chapter_summary: str,
    score_points: str,
) -> tuple[str, str]:
    """加载审阅提示词模板."""
    config = _load_template("review")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "")

    user_prompt = user_prompt_template.format(
        chapter_summary=chapter_summary,
        score_points=score_points,
    )
    return system_prompt, user_prompt


def load_param_check_prompt(assertion: str, content_excerpt: str) -> tuple[str, str]:
    """加载参数比对校验提示词模板（阶段 E1：review.yaml param_check 段）."""
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
    config = _load_template("consistency")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "{full_text}")
    user_prompt = user_prompt_template.format(full_text=full_text)
    return system_prompt, user_prompt


def load_requirements_prompt(score_points_json: str) -> tuple[str, str]:
    """加载技术需求梳理提示词模板（基于已确认评分点梳理应答需求）."""
    config = _load_template("requirements")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "{score_points_json}")
    user_prompt = user_prompt_template.format(score_points_json=score_points_json)
    return system_prompt, user_prompt
