"""审阅重写服务."""

from app.core.redact import redact
from app.services.llm_service import call_llm_with_schema
from app.services.prompt_loader import load_review_prompt


async def review_chapters(
    chapters: dict[str, str],
    score_points: list[dict],
) -> list[dict]:
    """审阅已生成章节，返回审阅意见列表."""
    # 构造评分点摘要
    sp_text = ""
    for sp in score_points:
        sp_text += f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
        sp_text += f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\n"

    # 构造章节摘要
    chapter_summary = ""
    for chapter_no, content in chapters.items():
        chapter_summary += f"\n\n### 章节 {chapter_no}\n{content[:500]}..."

    # 章节内容拼接提示词前脱敏（外发 LLM 安全铁律）
    system_prompt, user_prompt = load_review_prompt(
        chapter_summary=redact(chapter_summary),
        score_points=sp_text,
    )

    try:
        result = await call_llm_with_schema(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "review_result",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "comments": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "chapter_no": {"type": "string"},
                                        "comment": {"type": "string"},
                                        "action": {"type": "string"},
                                        "severity": {"type": "string"},
                                    },
                                    "required": ["chapter_no", "comment", "action"],
                                },
                            }
                        },
                        "required": ["comments"],
                    },
                },
            },
        )
        return result.get("comments", [])
    except Exception:
        return []  # 审阅失败不阻塞流程


async def rewrite_chapter(
    chapter_no: str,
    original_content: str,
    comment: str,
) -> str:
    """根据审阅意见重写章节."""
    from app.services.llm_service import call_llm_text

    system_prompt = (
        "你是专业的投标方案撰写专家。请根据审阅意见修改以下章节内容。"
        "保持专业性和完整性，直接输出修改后的内容。"
    )
    user_prompt = (
        f"## 章节 {chapter_no}\n\n"
        f"### 原始内容\n{original_content}\n\n"
        f"### 审阅意见\n{comment}\n\n"
        "请输出修改后的完整内容："
    )

    return await call_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.5,
    )
