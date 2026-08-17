"""章节生成服务 — RAG 增强 + LLM 生成."""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import redact
from app.services.llm_service import call_llm_stream, call_llm_text
from app.services.prompt_loader import load_chapter_prompt


def flatten_sections(sections: list) -> list[str]:
    """大纲子节拍平为标题列表（兼容 string[] 与二次编辑产物的嵌套树）.

    LLM 输出的 string[] 原样返回（不追加编号，保持既有章节提示词形态）；
    嵌套树 {title, children} 递归推导编号（1 / 1.1 / 1.1.1 …），供章节
    提示词与 RAG 检索使用。
    """
    if all(isinstance(s, str) for s in sections):
        return [s for s in sections if s]

    out: list[str] = []

    def _walk(nodes: list, prefix: str) -> None:
        for i, node in enumerate(nodes, 1):
            no = f"{prefix}{i}"
            if isinstance(node, str):
                if node.strip():
                    out.append(f"{no} {node.strip()}")
            elif isinstance(node, dict):
                title = str(node.get("title", "")).strip()
                if title:
                    out.append(f"{no} {title}")
                children = node.get("children") or []
                if children:
                    _walk(children, f"{no}.")
            # 其他类型忽略（防御脏数据）

    _walk(sections, "")
    return out


async def generate_chapter(
    chapter: dict,
    score_points: list[dict],
    tech_requirements: list[dict],
    project_id: uuid.UUID,
    context: str = "",
    db: AsyncSession | None = None,
    doc_ids: list[uuid.UUID] | None = None,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """生成单个章节内容.

    context: 调用方（retrieve 节点）传入的 RAG 检索素材；为空时尝试内部检索兜底。
    db: 调用方传入的真实 DB session；未传入时兜底检索自行打开 session。
    doc_ids: 资料库挂载配置 — 非 None 时兜底检索仅限定指定文档（None = 项目全量）。
    on_delta: 三期 S4 流式回调 — 非 None 时走流式生成并逐块回调，返回全文；
        None 时保持非流式调用（向后兼容）。
    """

    chapter_title = chapter.get("title", "")
    sections = flatten_sections(chapter.get("sections", []))

    # RAG 检索相关资料（优先使用调用方传入的检索素材）
    if not context:
        try:
            from app.core.database import async_session_factory
            from app.services.rag_service import get_embedding, retrieve_similar

            query = f"{chapter_title} {' '.join(sections)}"
            query_embedding = await get_embedding(query)
            if db is not None:
                similar_chunks = await retrieve_similar(
                    db=db,
                    project_id=project_id,
                    query_embedding=query_embedding,
                    top_k=10,
                    doc_ids=doc_ids,
                )
            else:
                async with async_session_factory() as session:
                    similar_chunks = await retrieve_similar(
                        db=session,
                        project_id=project_id,
                        query_embedding=query_embedding,
                        top_k=10,
                        doc_ids=doc_ids,
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

    if on_delta is not None:
        # 三期 S4：流式生成 — 逐块回调 delta，累积全文返回
        parts: list[str] = []
        async for delta in call_llm_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
        ):
            parts.append(delta)
            await on_delta(delta)
        return "".join(parts)

    content = await call_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.7,
    )

    return content
