"""章节 AI 辅助生成服务 — 可暂停流式生成（阶段 2）.

检索范围 = 项目挂载（库级 ∪ 文档级）∪ 本人个人库素材；
上下文 = 前文摘要 + 本章评分点 + 技术需求 + 用户自定义提示词；
暂停 = asyncio.Event 取消令牌置位，已生成部分按 append/overwrite 落库。
流式经 WS section_token（source="assist"）推送，与整章工作流生成区分。
"""

import asyncio
import time
import uuid

from sqlalchemy import select

from app.core.exceptions import BizError
from app.models.document import Document
from app.models.knowledge_base import SCOPE_PERSONAL, KnowledgeBase
from app.services import kb_base_service
from app.services.event_service import publish_event

# 任务注册表：project_id:chapter_no → 取消 Event（stop 端点置位）
_assist_tasks: dict[str, asyncio.Event] = {}

# 流式节流参数（与 nodes.write_node 口径一致，取先到者）
STREAM_FLUSH_CHARS = 40
STREAM_FLUSH_SECS = 0.2


def _task_key(project_id: uuid.UUID, chapter_no: str) -> str:
    return f"{project_id}:{chapter_no}"


def is_running(project_id: uuid.UUID, chapter_no: str) -> bool:
    return _task_key(project_id, chapter_no) in _assist_tasks


def stop_task(project_id: uuid.UUID, chapter_no: str) -> bool:
    """置位取消令牌；无进行中任务返回 False."""
    event = _assist_tasks.get(_task_key(project_id, chapter_no))
    if event is None:
        return False
    event.set()
    return True


async def resolve_assist_doc_ids(
    db,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    mounted_kb_ids: list[str] | None,
    mounted_doc_ids: list[str] | None,
) -> list[uuid.UUID]:
    """辅助生成检索范围：项目挂载 ∪ 本人个人库素材（显式 doc_id 列表）."""
    base_ids = await kb_base_service.resolve_mount_doc_ids(db, mounted_kb_ids, mounted_doc_ids)
    if base_ids is None:
        # 挂载未配置 = 项目全量：显式枚举项目文档，便于与个人库素材并集
        result = await db.execute(
            select(Document.id).where(Document.project_id == project_id)
        )
        base_ids = [row[0] for row in result.all()]

    personal_result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.scope == SCOPE_PERSONAL, KnowledgeBase.owner_id == user_id
        )
    )
    personal_base_ids = [row[0] for row in personal_result.all()]
    personal_docs = await kb_base_service.resolve_doc_ids(db, personal_base_ids)

    return sorted(set(base_ids) | set(personal_docs), key=str)


async def assist_generate(
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID,
    prompt: str = "",
    mode: str = "append",
) -> dict:
    """辅助生成章节内容（流式推 WS，可暂停），返回 {content, stopped, mode}.

    append = 追加到现有正文末尾；overwrite = 整章覆盖；
    暂停后已累积部分同样按 mode 落库（空部分不落库）。
    """
    from app.agents.nodes import _persist_chapter_content
    from app.core.database import async_session_factory
    from app.services import workflow_runtime
    from app.services.chapter_service import extract_chapter_summary, generate_chapter

    if mode not in ("append", "overwrite"):
        raise BizError(code=4000, message=f"mode 非法：{mode}")

    snapshot = await workflow_runtime.get_state(project_id)
    values = snapshot.values or {}
    outline = values.get("outline", [])
    # 子节编号 → 重定向父章生成（AI 仍章级产出），完成后切分返回子节片段
    subsection_no = chapter_no if "." in chapter_no else ""
    if subsection_no:
        chapter_no = chapter_no.rsplit(".", 1)[0]
    chapter = next((c for c in outline if str(c.get("chapter_no", "")) == chapter_no), None)
    if chapter is None:
        raise BizError(
            code=4004, message=f"章节 {subsection_no or chapter_no} 不在大纲中，无法辅助生成"
        )

    key = _task_key(project_id, chapter_no)
    if key in _assist_tasks:
        raise BizError(code=4000, message="该章节已有辅助生成任务进行中")
    stop_event = asyncio.Event()
    _assist_tasks[key] = stop_event

    title = chapter.get("title", "")
    existing = str(values.get("chapters", {}).get(chapter_no, "") or "")

    # 节流推送 section_token（source="assist" 区分整章工作流生成）
    token_buffer: list[str] = []
    token_buf_len = 0
    last_token_at = time.monotonic()

    async def _flush_tokens() -> None:
        nonlocal token_buf_len, last_token_at
        if not token_buffer:
            return
        await publish_event(
            str(project_id),
            {
                "type": "section_token",
                "chapter_no": chapter_no,
                "delta": "".join(token_buffer),
                "source": "assist",
            },
        )
        token_buffer.clear()
        token_buf_len = 0
        last_token_at = time.monotonic()

    async def on_delta(delta: str) -> None:
        nonlocal token_buf_len
        token_buffer.append(delta)
        token_buf_len += len(delta)
        overdue = time.monotonic() - last_token_at >= STREAM_FLUSH_SECS
        if token_buf_len >= STREAM_FLUSH_CHARS or overdue:
            await _flush_tokens()

    try:
        async with async_session_factory() as db:
            doc_ids = await resolve_assist_doc_ids(
                db,
                project_id,
                user_id,
                values.get("mounted_kb_ids"),
                values.get("mounted_doc_ids"),
            )

        summaries = dict(values.get("chapter_summaries", {}))
        prior_summaries = [
            {
                "chapter_no": c["chapter_no"],
                "title": summaries[c["chapter_no"]].get("title", c.get("title", "")),
                "summary": summaries[c["chapter_no"]].get("summary", ""),
            }
            for c in outline
            if c["chapter_no"] in summaries and c["chapter_no"] != chapter_no
        ]

        new_part = await generate_chapter(
            chapter=chapter,
            score_points=values.get("score_points", []),
            tech_requirements=values.get("tech_requirements", []),
            project_id=project_id,
            doc_ids=doc_ids,
            on_delta=on_delta,
            prior_summaries=prior_summaries,
            extra_instruction=prompt,
            stop_event=stop_event,
        )
    finally:
        _assist_tasks.pop(key, None)

    await _flush_tokens()  # 尾部缓冲兜底 flush（含暂停时的剩余 token）

    stopped = stop_event.is_set()
    if not new_part.strip():
        # 暂停过早或 LLM 空返回：不落库
        await publish_event(
            str(project_id),
            {
                "type": "section_done",
                "chapter_no": chapter_no,
                "title": title,
                "content": existing,
                "source": "assist",
                "stopped": stopped,
            },
        )
        return {"content": existing, "stopped": stopped, "mode": mode}

    # 按 mode 合成全文并双写（state.chapters + proposal_sections + 摘要重算）
    if mode == "append" and existing.strip():
        final_content = f"{existing.rstrip()}\n\n{new_part}"
    else:
        final_content = new_part

    new_summaries = dict(values.get("chapter_summaries", {}))
    new_summaries[chapter_no] = {
        "title": title,
        "summary": extract_chapter_summary(final_content),
    }
    await workflow_runtime.update_state(
        project_id,
        {"chapters": {chapter_no: final_content}, "chapter_summaries": new_summaries},
    )
    async with async_session_factory() as db:
        await _persist_chapter_content(
            db,
            str(project_id),
            chapter_no,
            title,
            final_content,
            status="draft",
            sections_tree=chapter.get("sections", []),
        )
        await db.commit()

    await publish_event(
        str(project_id),
        {
            "type": "section_done",
            "chapter_no": chapter_no,
            "title": title,
            "content": final_content,
            "source": "assist",
            "stopped": stopped,
        },
    )
    if subsection_no:
        # 子节分工：切分后仅返回目标子节片段（未命中降级返回整章）
        from app.services.chapter_service import split_chapter_to_sections

        for sec in split_chapter_to_sections(
            final_content, chapter.get("sections", []) or [], chapter_no
        ):
            if sec["section_id"] == subsection_no:
                return {"content": sec["content"], "stopped": stopped, "mode": mode}
    return {"content": final_content, "stopped": stopped, "mode": mode}
