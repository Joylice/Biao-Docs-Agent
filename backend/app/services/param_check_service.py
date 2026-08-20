"""参数比对校验服务 — 阶段 E1（SDD §3.5）.

从 ★ 评分点 criteria 抽取参数断言（≥/不低于/至少 → min；≤/不超过 → max，
万/亿单位归一化），与章节正文同类参数规则比对；规则不确定（正文无同单位
参数）时走 review.yaml param_check LLM 比对（mock 确定性 pass，异常降级 pass）。
"""

import json
import logging
import re

from app.services import settings_service
from app.services.llm_service import call_llm_text
from app.services.prompt_loader import load_param_check_prompt

logger = logging.getLogger(__name__)

# 数量级前缀归一化（2万路 → 20000 路）
_MULTIPLIERS = {"万": 10_000, "亿": 100_000_000}

# 单位字符集（中文量词 + 常见英文单位首字符），用于断言尾部匹配
_UNIT_CHARS = r"[A-Za-z%个条件路台套点位项名场次毫秒秒分钟小时天月年位次条户兆]"

# min 关键词在前（“不低于/不少于”不可被 max 的“低于/少于”误捕获）
_MIN_RE = re.compile(
    rf"(不低于|不少于|至少|达到|≥|>=)\s*(\d+(?:\.\d+)?)\s*([万亿])?({_UNIT_CHARS}+)?"
)
_MAX_RE = re.compile(
    rf"(?<!不)(不超过|不高于|不迟于|≤|<=|低于|少于|至多)\s*(\d+(?:\.\d+)?)\s*([万亿])?({_UNIT_CHARS}+)?"
)


def extract_assertions(text: str) -> list[dict]:
    """从判定标准文本抽取参数断言 [{direction, value, unit, raw}]."""
    if not text:
        return []
    assertions: list[dict] = []
    for pattern, direction in ((_MIN_RE, "min"), (_MAX_RE, "max")):
        for m in pattern.finditer(text):
            num, mult, unit = m.group(2), m.group(3), m.group(4)
            value = float(num) * _MULTIPLIERS.get(mult or "", 1)
            assertions.append(
                {
                    "direction": direction,
                    "value": value,
                    "unit": (unit or "").strip(),
                    "raw": m.group(0).strip(),
                }
            )
    return assertions


def find_unit_values(content: str, unit: str) -> list[float]:
    """在正文中查找同单位数值（含万/亿前缀归一化），按出现顺序返回."""
    if not content or not unit:
        return []
    pattern = re.compile(rf"(\d+(?:\.\d+)?)\s*([万亿])?{re.escape(unit)}")
    values: list[float] = []
    for m in pattern.finditer(content):
        num, mult = m.groups()
        values.append(float(num) * _MULTIPLIERS.get(mult or "", 1))
    return values


async def _llm_judge(assertion: dict, content: str) -> bool:
    """规则不确定时的 LLM 比对：返回是否通过（异常/解析失败降级 pass）."""
    try:
        system_prompt, user_prompt = load_param_check_prompt(
            assertion=json.dumps(assertion, ensure_ascii=False),
            content_excerpt=content[:2000],
        )
        raw = await call_llm_text(
            system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0
        )
        data = json.loads(raw)
        return bool(data.get("pass", True))
    except Exception as e:
        logger.warning("参数比对 LLM 校验失败（降级 pass）: %s", e)
        return True


async def check_chapter_params(content: str, score_points: list[dict]) -> list[str]:
    """★ 评分点参数断言 vs 章节正文：返回 param_mismatch issue 列表."""
    issues: list[str] = []
    for sp in score_points:
        if not sp.get("is_star"):
            continue
        for assertion in extract_assertions(sp.get("criteria") or ""):
            if not assertion["unit"]:
                continue  # 无单位的数值断言（如分值）不参与正文比对
            values = find_unit_values(content, assertion["unit"])
            if not values:
                # 规则不确定 → mock 确定性 pass / 真实模式 LLM 比对
                if await settings_service.is_mock_enabled():
                    continue
                if await _llm_judge(assertion, content):
                    continue
                issues.append(
                    f"参数不符评分点 {sp.get('clause_no', '')}：要求{assertion['raw']}，"
                    "正文未明确满足（LLM 比对未通过）"
                )
                continue
            if assertion["direction"] == "min" and max(values) < assertion["value"]:
                issues.append(
                    f"参数不符评分点 {sp.get('clause_no', '')}：要求{assertion['raw']}，"
                    f"正文最大仅 {max(values):g}{assertion['unit']}"
                )
            elif assertion["direction"] == "max" and min(values) > assertion["value"]:
                issues.append(
                    f"参数不符评分点 {sp.get('clause_no', '')}：要求{assertion['raw']}，"
                    f"正文最小为 {min(values):g}{assertion['unit']}"
                )
    return issues
