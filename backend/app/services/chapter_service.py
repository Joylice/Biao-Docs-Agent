"""章节生成服务 — RAG 增强 + LLM 生成."""

import uuid

from app.core.redact import redact
from app.services.llm_service import call_llm_text
from app.services.prompt_loader import load_chapter_prompt


async def generate_chapter(
    chapter: dict,
    score_points: list[dict],
    tech_requirements: list[dict],
    project_id: uuid.UUID,
    context: str = "",
) -> str:
    """生成单个章节内容.

    context: 调用方（retrieve 节点）传入的 RAG 检索素材；为空时尝试内部检索兜底。
    """
    chapter_title = chapter.get("title", "")
    sections = chapter.get("sections", [])

    # RAG 检索相关资料（优先使用调用方传入的检索素材）
    if not context:
        try:
            from app.services.rag_service import get_embedding, retrieve_similar

            query = f"{chapter_title} {' '.join(sections)}"
            query_embedding = await get_embedding(query)
            similar_chunks = await retrieve_similar(
                db=None,  # 由 retrieve 节点提供素材；此处仅为兼容旧调用
                project_id=project_id,
                query_embedding=query_embedding,
                top_k=10,
            )
            context = "\n\n---\n\n".join(c.content for c in similar_chunks)
        except Exception:
            context = ""  # RAG 失败时降级为无上下文

    # 构造评分点覆盖
    sp_text = ""
    for sp in score_points:
        sp_text += f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
        sp_text += f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\n"

    # 构造技术需求覆盖
    tr_text = ""
    for tr in tech_requirements:
        tr_text += f"- [{tr.get('category', '')}] {tr.get('description', '')}\n"

    # RAG 语料拼接提示词前脱敏（外发 LLM 安全铁律）
    context = redact(context)

    system_prompt, user_prompt = load_chapter_prompt(
        chapter_title=chapter_title,
        sections=sections,
        context=context,
        score_points=sp_text,
        tech_requirements=tr_text,
    )

    content = await call_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.7,
    )

    return content
