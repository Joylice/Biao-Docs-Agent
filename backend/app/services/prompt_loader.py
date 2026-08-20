"""提示词模板加载器."""

from pathlib import Path

import yaml

from app.core.exceptions import BizError

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


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


def load_outline_prompt(
    score_points: list[dict],
    tech_requirements: list[dict],
) -> tuple[str, str]:
    """加载大纲生成提示词模板."""
    config = _load_template("outline")
    system_prompt = config.get("system_prompt", "")
    user_prompt_template = config.get("user_prompt", "")

    sp_text = "\n".join(
        f"- {sp.get('clause_no', '')} {sp.get('item', '')}: 分值{sp.get('score', '?')}"
        for sp in score_points
    )
    tr_text = "\n".join(
        f"- [{tr.get('category', '')}] {tr.get('description', '')}" for tr in tech_requirements
    )

    user_prompt = user_prompt_template.format(score_points=sp_text, tech_requirements=tr_text)
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
