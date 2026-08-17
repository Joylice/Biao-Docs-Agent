"""内容改进建议服务 — 评分点覆盖度驱动的规则建议 + LLM 建议（失败降级为空）.

采纳执行复用既有 rewrite-chapter 端点（前端确认后调用，人工确认门禁），
本服务不产出 suggestion_id、不做应用逻辑。
"""

import logging

from app.core.redact import redact
from app.services import settings_service
from app.services.llm_service import call_llm_with_schema

logger = logging.getLogger(__name__)


def _rule_suggestions(
    chapters: dict[str, str], score_points: list[dict], chapter_no: str | None = None
) -> list[dict]:
    """确定性规则建议：章节内容未提及的评分点 → 对最相关章建议补充.

    最相关章 = 内容包含评分点 item 关键词的章（首个命中）；无命中取末章。
    指定 chapter_no 时仅对该章生成建议（命中自身或作为末章兜底）。
    """
    if not chapters:
        return []
    targets = [chapter_no] if chapter_no else list(chapters.keys())

    suggestions: list[dict] = []
    for sp in score_points:
        clause_no = str(sp.get("clause_no", "")).strip()
        item = str(sp.get("item", "") or "").strip()
        if not clause_no:
            continue
        # 最相关章：内容含关键词的章优先（确定性）；否则末章
        matched = [c for c in targets if item and item in chapters.get(c, "")]
        target = matched[0] if matched else targets[-1]
        if item and item in chapters.get(target, ""):
            continue  # 目标章已覆盖该评分点
        suggestions.append(
            {
                "chapter_no": target,
                "issue": f"未覆盖评分点 {clause_no}（{item}）",
                "suggestion": f"建议在章节 {target} 中补充「{item}」相关内容，"
                f"对齐评分标准：{sp.get('criteria', '')}",
                "severity": "high" if sp.get("is_star") else "medium",
            }
        )
    return suggestions


def _mock_fallback_suggestions(
    chapters: dict[str, str], score_points: list[dict], chapter_no: str | None = None
) -> list[dict]:
    """mock 占位数据兜底：item 为 "mock" 且章节内容含 "mock" 字样（占位同质化）

    使内容匹配判定自洽为空，此时对占位评分点生成确定性建议，
    保证建议链路在 mock 下可测（E2E 可断言）。真实数据全覆盖不触发本兜底。
    """
    if not chapters:
        return []
    for sp in score_points:
        if str(sp.get("item", "") or "") != "mock":
            continue
        target = chapter_no or list(chapters.keys())[-1]
        return [
            {
                "chapter_no": target,
                "issue": f"未覆盖评分点 {sp.get('clause_no', '')}（mock 占位数据）",
                "suggestion": f"建议在章节 {target} 中补充对应评分点内容，"
                "对齐评分标准（mock 模式确定性建议）",
                "severity": "high" if sp.get("is_star") else "medium",
            }
        ]
    return []


async def build_section_suggestions(
    chapters: dict[str, str],
    score_points: list[dict],
    chapter_no: str | None = None,
) -> list[dict]:
    """生成内容改进建议：mock 走规则建议；生产走 LLM schema；LLM 失败降级为空."""
    if await settings_service.is_mock_enabled():
        return _rule_suggestions(chapters, score_points, chapter_no) or _mock_fallback_suggestions(
            chapters, score_points, chapter_no
        )
    try:
        sp_text = "".join(
            f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
            f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\n"
            for sp in score_points
        )
        chapter_text = "".join(
            f"\n\n### 章节 {c}\n{content[:800]}..." for c, content in chapters.items()
        )
        focus = f"（重点分析章节 {chapter_no}）" if chapter_no else "（分析全部已生成章节）"
        result = await call_llm_with_schema(
            system_prompt=(
                "你是投标方案审阅专家。基于评分点与已生成章节内容，给出内容改进建议："
                "指出未覆盖的评分点或内容薄弱处，建议具体补充方向，并标注严重程度。"
            ),
            # 外发前脱敏（安全铁律：出口兜底前服务层显式 redact）
            user_prompt=redact(f"评分点：\n{sp_text}\n\n章节内容：\n{chapter_text}\n{focus}"),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "section_suggestions",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "suggestions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "chapter_no": {"type": "string"},
                                        "issue": {"type": "string"},
                                        "suggestion": {"type": "string"},
                                        "severity": {"type": "string"},
                                    },
                                    "required": ["chapter_no", "issue", "suggestion"],
                                },
                            }
                        },
                        "required": ["suggestions"],
                    },
                },
            },
        )
        return [
            s for s in result.get("suggestions", []) if isinstance(s, dict) and s.get("chapter_no")
        ]
    except Exception:
        logger.exception("内容建议 LLM 调用失败，降级为空建议")
        return []
