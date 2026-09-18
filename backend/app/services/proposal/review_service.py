"""审阅重写服务."""

import logging
from typing import Any

from app.core.redact import redact
from app.services.infra.prompt_loader import load_review_prompt
from app.services.llm.llm_service import call_llm_with_schema

logger = logging.getLogger(__name__)


async def review_chapters(
    chapters: dict[str, str],
    score_points: list[dict[str, Any]],
    project_id: str | None = None,
) -> list[dict[str, Any]]:
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
    system_prompt, user_prompt = await load_review_prompt(
        chapter_summary=redact(chapter_summary),
        score_points=sp_text,
    )

    # 外部工具取证前置（stage=review 绑定搜索工具时；无绑定/mock/异常原样返回）
    from app.services.infra.tools.prefetch import prefetch_external_evidence

    system_prompt, user_prompt = await prefetch_external_evidence(
        "review",
        system_prompt,
        user_prompt,
        project_id,
        intent="依据评分标准逐条审查章节内容，可参考外部标准/规范原文佐证",
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
            stage_key="review",
            project_id=project_id,
        )
        # result 来自 schema 化 LLM 调用，对 mypy 是 Any；显式落到声明返回类型
        comments: list[dict[str, Any]] = result.get("comments", [])
        return comments
    except Exception:
        # 审阅失败不阻塞流程（观测：返回空即审阅环节被跳过）
        logger.warning("章节审阅 LLM 调用失败，返回空审阅意见", exc_info=True)
        return []


async def rewrite_chapter(
    chapter_no: str,
    original_content: str,
    comment: str,
) -> str:
    """根据审阅意见重写章节."""
    from app.services.llm.llm_service import call_llm_text

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
        stage_key="review",
    )
