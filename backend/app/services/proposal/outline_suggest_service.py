"""大纲优化建议服务 — 覆盖矩阵缺口驱动的规则建议 + LLM 建议（含降级）.

设计约定：
- suggestion_id 由服务端统一编码（携带操作参数），apply_outline_suggestions
  无需重建建议即可解码应用 —— mock 规则建议与 LLM 建议均闭环可用；
- mock 模式 / LLM 失败 → 确定性规则建议（E2E 可断言）；
- 建议为瞬态数据（不落库），最终执行仍由 confirm-outline 人工确认完成。
"""

import base64
import json
import logging

from app.core.redact import redact
from app.services.infra import settings_service
from app.services.llm.llm_service import call_llm_with_schema

logger = logging.getLogger(__name__)

_SUGGEST_TYPES = ("add_section", "add_chapter", "rename", "merge")


# ───────────────────────── suggestion_id 编码/解码 ─────────────────────────


def _b64(text: str) -> str:
    """URL-safe base64（suggestion_id 中的标题等自由文本）."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(text: str) -> str:
    try:
        return base64.urlsafe_b64decode(text.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def _encode_suggestion_id(suggestion: dict) -> str:
    """把建议编码进 suggestion_id（apply 可解码应用，无需重建建议）.

    格式：{type}:{参数...}:{b64(标题)}，参数按类型取 target 字段：
    add_section → chapter_no:clause_no；add_chapter → clause_no；
    rename/merge → chapter_no。
    """
    target = suggestion.get("target") or {}
    parts = [suggestion.get("suggestion_type", "")]
    if suggestion.get("suggestion_type") == "add_section":
        parts.extend([str(target.get("chapter_no", "")), str(target.get("clause_no", ""))])
    elif suggestion.get("suggestion_type") == "add_chapter":
        parts.append(str(target.get("clause_no", "")))
    else:  # rename / merge
        parts.append(str(target.get("chapter_no", "")))
    parts.append(_b64(str(target.get("title", "") or "")))
    return ":".join(parts)


def _decode_suggestion_id(suggestion_id: str) -> dict | None:
    """解码 suggestion_id → {type, chapter_no, clause_no, title}；非法返回 None."""
    parts = suggestion_id.split(":")
    if len(parts) < 2 or parts[0] not in _SUGGEST_TYPES:
        return None
    kind = parts[0]
    decoded: dict[str, str] = {"type": kind, "chapter_no": "", "clause_no": "", "title": ""}
    if kind == "add_section":
        if len(parts) < 4:
            return None
        decoded["chapter_no"], decoded["clause_no"] = parts[1], parts[2]
        decoded["title"] = _unb64(parts[3])
    elif kind == "add_chapter":
        if len(parts) < 3:
            return None
        decoded["clause_no"] = parts[1]
        decoded["title"] = _unb64(parts[2])
    else:
        if len(parts) < 3:
            return None
        decoded["chapter_no"] = parts[1]
        decoded["title"] = _unb64(parts[2])
    return decoded


# ───────────────────────── 规则建议（确定性） ─────────────────────────


def _covered_clauses(outline: list[dict]) -> set[str]:
    """汇总大纲已覆盖的评分点子句号."""
    covered: set[str] = set()
    for chapter in outline:
        for clause in chapter.get("covered_clauses") or []:
            covered.add(str(clause).strip())
    return covered


def _rule_suggestions(score_points: list[dict], outline: list[dict]) -> list[dict]:
    """覆盖矩阵缺口 → 规则建议：未覆盖评分点补小节；空大纲补章节."""
    if not outline:
        # 空大纲：建议新增章节（标题取第一条未覆盖评分点，最高优先级在前）
        for sp in score_points:
            clause_no = str(sp.get("clause_no", "")).strip()
            if clause_no:
                title = str(sp.get("item", "") or "")
                return [
                    _make_suggestion("add_chapter", {"clause_no": clause_no, "title": title}, sp)
                ]
        return []

    covered = _covered_clauses(outline)
    target = outline[-1]  # 目标章 = 末章（确定性）
    suggestions: list[dict] = []
    for sp in score_points:
        clause_no = str(sp.get("clause_no", "")).strip()
        if not clause_no or clause_no in covered:
            continue
        item = str(sp.get("item", "") or "")
        suggestions.append(
            _make_suggestion(
                "add_section",
                {"chapter_no": target["chapter_no"], "clause_no": clause_no, "title": item},
                sp,
                f"在章节 {target['chapter_no']} 增加小节：{item}",
            )
        )
    return suggestions


def _make_suggestion(
    suggestion_type: str,
    target: dict,
    score_point: dict,
    suggested_action: str = "",
) -> dict:
    """组装建议（含服务端编码的 suggestion_id）."""
    clause_no = target.get("clause_no", "")
    item = target.get("title", "")
    reason = f"未覆盖评分点 {clause_no}（{item}），建议补充对应内容"
    if suggestion_type == "add_chapter":
        reason = f"大纲为空，建议新增章节覆盖评分点 {clause_no}（{item}）"
    suggestion = {
        "suggestion_type": suggestion_type,
        "target": target,
        "reason": reason,
        "suggested_action": suggested_action or reason,
    }
    suggestion["suggestion_id"] = _encode_suggestion_id(suggestion)
    return suggestion


def _finalize_llm_suggestion(raw: dict) -> dict | None:
    """规范化 LLM 建议并编码 suggestion_id；结构缺失时丢弃."""
    suggestion_type = str(raw.get("suggestion_type", "")).strip()
    if suggestion_type not in _SUGGEST_TYPES:
        return None
    target = raw.get("target") or {}
    suggestion = {
        "suggestion_type": suggestion_type,
        "target": target,
        "reason": str(raw.get("reason", "") or ""),
        "suggested_action": str(raw.get("suggested_action", "") or ""),
    }
    suggestion["suggestion_id"] = _encode_suggestion_id(suggestion)
    return suggestion


# ───────────────────────── 对外接口 ─────────────────────────


def _mock_fallback_suggestions(score_points: list[dict]) -> list[dict]:
    """mock 占位数据兜底：LLM 占位值（clause_no/item 均为 "mock"）使覆盖判定自洽为空，

    此时对占位评分点生成确定性 add_chapter 建议，保证建议链路在 mock 下可测（E2E 可断言）。
    真实数据全覆盖（无占位值）不触发本兜底，仍返回空建议。
    """
    for sp in score_points:
        if str(sp.get("clause_no", "") or "") != "mock":
            continue
        suggestion = {
            "suggestion_type": "add_chapter",
            "target": {"clause_no": "mock", "title": "补充章节"},
            "reason": f"评分点 {sp.get('clause_no', '')} 为 mock 占位数据，"
            "建议新增章节承载对应内容",
            "suggested_action": "新增章节：补充章节",
        }
        suggestion["suggestion_id"] = _encode_suggestion_id(suggestion)
        return [suggestion]
    return []


async def build_outline_suggestions(score_points: list[dict], outline: list[dict]) -> list[dict]:
    """生成大纲优化建议：mock/降级走规则建议，生产走 LLM schema."""
    if await settings_service.is_mock_enabled():
        return _rule_suggestions(score_points, outline) or _mock_fallback_suggestions(score_points)
    try:
        sp_text = "".join(
            f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
            f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\n"
            for sp in score_points
        )
        outline_text = json.dumps(outline, ensure_ascii=False)
        result = await call_llm_with_schema(
            system_prompt=(
                "你是投标方案大纲优化专家。根据评分点覆盖矩阵与当前大纲，"
                "给出优化建议：未覆盖评分点需补充章节或小节；标题不当可改名；"
                "内容重叠可合并。每条建议给出类型、目标、理由与建议动作。"
            ),
            # 外发前脱敏（安全铁律：出口兜底前服务层显式 redact）
            user_prompt=redact(f"评分点：\n{sp_text}\n\n当前大纲：\n{outline_text}"),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "outline_suggestions",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "suggestions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "suggestion_type": {"type": "string"},
                                        "target": {
                                            "type": "object",
                                            "properties": {
                                                "chapter_no": {"type": "string"},
                                                "clause_no": {"type": "string"},
                                                "title": {"type": "string"},
                                            },
                                            "required": [],
                                        },
                                        "reason": {"type": "string"},
                                        "suggested_action": {"type": "string"},
                                    },
                                    "required": [
                                        "suggestion_type",
                                        "reason",
                                        "suggested_action",
                                    ],
                                },
                            }
                        },
                        "required": ["suggestions"],
                    },
                },
            },
        )
        suggestions = [
            s for s in (_finalize_llm_suggestion(s) for s in result.get("suggestions", [])) if s
        ]
        if suggestions:
            return suggestions
    except Exception:
        logger.exception("大纲建议 LLM 调用失败，降级为规则建议")
    return _rule_suggestions(score_points, outline)


def apply_outline_suggestions(outline: list[dict], adopted: list[str]) -> list[dict]:
    """按已采纳建议的 suggestion_id 应用到大纲（纯函数，不写 state）.

    add_section → 目标章 sections 追加标题（幂等去重）；
    add_chapter → 末尾追加新章（章节号递增，携带 covered_clauses）；
    rename → 目标章标题替换；merge 需人工在大纲编辑中合并，此处跳过；
    未知/非法 id 忽略。
    """
    result: list[dict] = [dict(c) for c in outline]
    for suggestion_id in adopted:
        op = _decode_suggestion_id(suggestion_id)
        if op is None:
            continue
        if op["type"] == "add_section":
            chapter = next(
                (c for c in result if str(c.get("chapter_no", "")) == op["chapter_no"]), None
            )
            if chapter is None or not op["title"]:
                continue
            sections = list(chapter.get("sections") or [])
            if op["title"] not in sections:
                sections.append(op["title"])
            chapter["sections"] = sections
        elif op["type"] == "add_chapter":
            nums = [int(c["chapter_no"]) for c in result if str(c.get("chapter_no", "")).isdigit()]
            new_no = str(max(nums) + 1) if nums else "1"
            result.append(
                {
                    "chapter_no": new_no,
                    "title": op["title"],
                    "sections": [],
                    "covered_clauses": [op["clause_no"]] if op["clause_no"] else [],
                }
            )
        elif op["type"] == "rename":
            chapter = next(
                (c for c in result if str(c.get("chapter_no", "")) == op["chapter_no"]), None
            )
            if chapter is not None and op["title"]:
                chapter["title"] = op["title"]
        # merge：人工处理（编码 id 可解码但应用跳过）
    return result
