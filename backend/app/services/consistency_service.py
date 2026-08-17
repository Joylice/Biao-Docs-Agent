"""全文一致性检查服务 — integrate 前一次 LLM 调用检查全文质量.

检查项：术语冲突、重复段落、编号断裂；产出 issues 列表交节点决策
（可修复走一轮定向重写，否则告警不阻塞导出）。
mock 模式直通空 issues（保持 E2E 确定性）。
"""

import logging

from app.services import settings_service
from app.services.llm_service import call_llm_with_schema
from app.services.prompt_loader import load_consistency_prompt

logger = logging.getLogger(__name__)

CONSISTENCY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "consistency_issues",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chapter_no": {"type": "string"},
                            "type": {
                                "type": "string",
                                "description": "terminology|duplicate|numbering",
                            },
                            "description": {"type": "string"},
                            "fixable": {"type": "boolean"},
                        },
                        "required": ["chapter_no", "type", "description", "fixable"],
                    },
                }
            },
            "required": ["issues"],
        },
    },
}


async def check_consistency(chapters: dict[str, str], outline: list[dict]) -> list[dict]:
    """检查全文一致性，返回 issues 列表；mock/空章节/非法响应均返回 []."""
    if not chapters:
        return []
    if await settings_service.is_mock_enabled():
        return []

    # 全文按大纲顺序拼接送检（章节号 + 标题 + 正文）
    parts: list[str] = []
    for chapter in outline:
        no = chapter.get("chapter_no", "")
        content = chapters.get(no, "")
        if content:
            parts.append(f"## 第{no}章 {chapter.get('title', '')}\n\n{content}")
    # 大纲外的残余章节兜底（防御脏状态）
    known = {c.get("chapter_no", "") for c in outline}
    for no, content in chapters.items():
        if no not in known and content:
            parts.append(f"## 第{no}章\n\n{content}")

    system_prompt, user_prompt = load_consistency_prompt("\n\n---\n\n".join(parts))
    result = await call_llm_with_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=CONSISTENCY_SCHEMA,
    )

    issues = result.get("issues") if isinstance(result, dict) else None
    if not isinstance(issues, list):
        logger.warning("一致性检查响应结构非法，降级返回空 issues")
        return []
    return [i for i in issues if isinstance(i, dict)]
