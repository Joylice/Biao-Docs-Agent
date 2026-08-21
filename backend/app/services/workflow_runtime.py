"""工作流运行时服务 — LangGraph 编排与 checkpointer 生命周期（对齐 SDD §6）.

分层约定：API 层仅调用本模块，不直接操作 checkpointer / langgraph。

Checkpointer：
- 生产环境使用 AsyncPostgresSaver + 独立 psycopg AsyncConnectionPool
  （不与 app 的 SQLAlchemy AsyncSession 混用），由 app lifespan 初始化/释放；
- thread_id = str(project_id)；
- 测试可通过 set_saver(InMemorySaver()) 注入替代。
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from app.agents.graph import compile_workflow, get_async_postgres_saver
from app.core.config import settings
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

# ───────────────────────── checkpointer 生命周期 ─────────────────────────

_saver: Any = None
_pool: Any = None
_background_tasks: set[asyncio.Task] = set()
# 在途执行集合（thread_id 维度）：同一项目重复 start 时拒绝，任务结束自动移除
_running: set[str] = set()


def _pg_conninfo() -> str:
    """SQLAlchemy 风格 URL → psycopg conninfo（去掉 +psycopg 驱动后缀）."""
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def init_checkpointer() -> None:
    """初始化 AsyncPostgresSaver（独立连接池）。app lifespan 启动时调用."""
    global _saver, _pool
    if _saver is not None:
        return
    pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncConnectionPool

        pool = AsyncConnectionPool(
            _pg_conninfo(),
            min_size=2,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            timeout=settings.workflow_pool_timeout,
            open=False,
        )
        await pool.open()
        saver = get_async_postgres_saver()(conn=pool)
        await saver.setup()
    except Exception:
        logger.exception("工作流 checkpointer 初始化失败（工作流接口将不可用）")
        if pool is not None:
            # 池已打开但初始化失败：先关闭已打开的池，避免连接泄漏
            with contextlib.suppress(Exception):
                await pool.close()
        return
    _pool = pool
    _saver = saver


async def shutdown_checkpointer() -> None:
    """释放 checkpointer 连接池。app lifespan 关闭时调用."""
    global _saver, _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:  # pragma: no cover - 释放失败仅告警
            logger.warning("关闭 checkpointer 连接池失败", exc_info=True)
    _pool = None
    _saver = None


def set_saver(saver: Any) -> None:
    """注入 checkpointer（测试用 InMemorySaver 替代 AsyncPostgresSaver）."""
    global _saver
    _saver = saver


def get_saver() -> Any:
    """获取当前 checkpointer；未初始化时抛业务异常."""
    if _saver is None:
        raise BizError(code=5005, message="工作流状态存储未初始化")
    return _saver


# ───────────────────────── 图执行编排 ─────────────────────────


def _graph():
    """按当前 checkpointer 编译工作流图."""
    return compile_workflow(checkpointer=get_saver())


def _config(project_id: uuid.UUID | str) -> dict:
    """thread_id = project_id（对齐 SDD §6）."""
    return {"configurable": {"thread_id": str(project_id)}}


async def run_workflow(project_id: uuid.UUID | str, user_id: uuid.UUID | str) -> dict:
    """首次执行工作流；遇 HITL interrupt 自动停下并返回当前结果."""
    return await _graph().ainvoke(
        {"project_id": str(project_id), "user_id": str(user_id)},
        _config(project_id),
    )


async def resume_workflow(project_id: uuid.UUID | str, resume_value: Any) -> dict:
    """恢复被 interrupt 的工作流（confirm_score_points / confirm_outline / review）."""
    return await _graph().ainvoke(Command(resume=resume_value), _config(project_id))


async def get_state(project_id: uuid.UUID | str):
    """读取 thread 最新 checkpoint 快照（StateSnapshot）."""
    return await _graph().aget_state(_config(project_id))


def pending_interrupt(snapshot: Any) -> dict | None:
    """从快照中提取当前挂起的 HITL interrupt payload，无则 None."""
    for task in snapshot.tasks or ():
        interrupts = getattr(task, "interrupts", None)
        if interrupts:
            return interrupts[0].value
    return None


async def ensure_pending_interrupt(project_id: uuid.UUID | str, expected_type: str) -> None:
    """resume 前置校验：当前 thread 必须挂起期望类型的 interrupt.

    无 pending interrupt 或类型不匹配 → 抛业务错误（4009），
    避免 ainvoke(Command(resume=...)) 空恢复污染 state.error。
    """
    snapshot = await get_state(project_id)
    payload = pending_interrupt(snapshot)
    if payload is None:
        raise BizError(code=4009, message="当前没有待处理的工作流中断，操作无效")
    if payload.get("type") != expected_type:
        raise BizError(
            code=4009,
            message=(
                f"当前待处理的中断类型为 {payload.get('type')}，与本次操作（{expected_type}）不匹配"
            ),
        )


async def get_status_dict(project_id: uuid.UUID | str) -> dict:
    """聚合 checkpointer 状态为 API status 响应结构."""
    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    return {
        "workflow_id": str(project_id),
        "phase": values.get("current_phase", "init"),
        "progress": values.get("progress", 0.0),
        "score_points": values.get("score_points", []),
        "outline": values.get("outline", []),
        "chapters": values.get("chapters", {}),
        "review_action": values.get("review_action", ""),
        "review_feedback": values.get("review_feedback", {}),
        "export_status": values.get("export_status", ""),
        "export_storage_key": values.get("export_storage_key", ""),
        "error": values.get("error", ""),
        "interrupt": pending_interrupt(snapshot),
    }


async def update_state(project_id: uuid.UUID | str, values: dict) -> None:
    """经 checkpointer 更新 thread 状态（如替换大纲、合并章节）."""
    await _graph().aupdate_state(_config(project_id), values)


async def regenerate_outline(project_id: uuid.UUID | str) -> list[dict]:
    """重新生成大纲 — resume confirm_outline 节点（action=regenerate）.

    仅允许 confirm_outline interrupt 挂起时调用（大纲尚未确认）；节点内复用
    generate_outline_node 以最新提示词重新生成并落库，随后再次 interrupt 挂起
    （保留 pending interrupt，前端可继续确认），返回新大纲。
    """
    await ensure_pending_interrupt(project_id, "confirm_outline")

    result = await resume_workflow(project_id, {"action": "regenerate"})
    outline = result.get("outline", [])
    if not outline:
        raise BizError(code=5011, message=result.get("error") or "重新生成大纲失败")
    return outline


async def rewrite_chapter(project_id: uuid.UUID | str, chapter_no: str, comment: str) -> str:
    """取 state 中的章节原文重写，并经 checkpointer 回写 chapters.

    与图内 rewrite 节点一致，重写走 review_service.rewrite_chapter；
    chapters 通道为合并语义（operator.or_），只覆盖指定章节。
    """
    snapshot = await get_state(project_id)
    chapters = (snapshot.values or {}).get("chapters", {})
    original = chapters.get(chapter_no)
    if not original:
        raise BizError(code=4004, message=f"章节 {chapter_no} 尚未生成，无法重写")

    from app.services.review_service import rewrite_chapter as llm_rewrite

    new_content = await llm_rewrite(
        chapter_no=chapter_no,
        original_content=original,
        comment=comment,
    )
    await update_state(project_id, {"chapters": {chapter_no: new_content}})
    return new_content


async def save_section_edit(
    db,
    project_id: uuid.UUID | str,
    chapter_no: str,
    content: str,
) -> None:
    """人工编辑章节/子节直接落库：state（chapters + 摘要重算）与 DB 同步.

    与 rewrite_chapter 的差异：不经 LLM，内容来自人工编辑；落库 status=review
    （对齐 write_node 的 _upsert_section 字段口径）。支持子节编号（如 1.1）：
    子节行更新后按自然序拼接同章子节行重建父章全文回写 state。
    章级编辑若大纲含嵌套子节则同步切分刷新子节行（子节真源一致）。
    DB 提交由 API 层统一 commit。
    """
    from sqlalchemy import select

    from app.agents.nodes import _persist_chapter_content, _upsert_section
    from app.models.proposal import ProposalSection
    from app.services.chapter_service import extract_chapter_summary
    from app.services.export_service import natural_sort_key

    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    chapters = values.get("chapters", {})
    outline = values.get("outline", [])
    is_subsection = "." in chapter_no
    parent_no = chapter_no.rsplit(".", 1)[0] if is_subsection else chapter_no

    if is_subsection:
        if parent_no not in chapters:
            raise BizError(code=4004, message=f"章节 {parent_no} 尚未生成，无法保存子节")
        # 子节标题取大纲嵌套树（缺失时保留既有行标题）
        title = ""
        chapter = next((c for c in outline if str(c.get("chapter_no", "")) == parent_no), None)
        if chapter:
            from app.services.chapter_service import numbered_sections

            title = next(
                (
                    t
                    for no, t in numbered_sections(chapter.get("sections", []) or [], parent_no)
                    if no == chapter_no
                ),
                "",
            )
        await _upsert_section(db, str(project_id), chapter_no, title, content, status="review")
        # 自然序拼接同章子节行重建父章全文（1.1 < 1.2 < 2）
        sec_result = await db.execute(
            select(ProposalSection).where(
                ProposalSection.project_id == uuid.UUID(str(project_id)),
                ProposalSection.section_id.startswith(f"{parent_no}."),
            )
        )
        sec_rows = sorted(sec_result.scalars().all(), key=lambda s: natural_sort_key(s.section_id))
        merged = "\n\n".join(s.content_md for s in sec_rows if s.content_md)
        target_no, target_content = parent_no, merged or content
    else:
        if chapter_no not in chapters:
            raise BizError(code=4004, message=f"章节 {chapter_no} 尚未生成，无法保存")
        target_no, target_content = chapter_no, content

    # 标题取大纲（章节均来自大纲生成）；缺失时保留既有摘要中的标题
    title = next((c.get("title", "") for c in outline if c.get("chapter_no") == target_no), "")
    if not title:
        title = (values.get("chapter_summaries", {}).get(target_no) or {}).get("title", "")

    summaries = dict(values.get("chapter_summaries", {}))
    summaries[target_no] = {"title": title, "summary": extract_chapter_summary(target_content)}
    await update_state(
        project_id,
        {"chapters": {target_no: target_content}, "chapter_summaries": summaries},
    )
    if not is_subsection:
        chapter = next((c for c in outline if c.get("chapter_no") == chapter_no), None)
        await _persist_chapter_content(
            db,
            str(project_id),
            chapter_no,
            title,
            content,
            status="review",
            sections_tree=(chapter or {}).get("sections", []),
        )


async def generate_chapter_draft(project_id: uuid.UUID | str, chapter_no: str) -> str:
    """分工编制：LLM 生成章节初稿并回写 state + proposal_sections（status=draft）.

    复用图内同一 generate_chapter 链路（RAG 检索 + 脱敏 + mock 降级）；
    与图内 write 节点的差异：不推进工作流阶段，仅产出初稿供人工编制。
    子节编号（如 1.1）：生成整章后切分，仅返回目标子节片段（AI 仍章级产出）。
    """
    from app.agents.nodes import _persist_chapter_content
    from app.core.database import async_session_factory
    from app.services.chapter_service import (
        extract_chapter_summary,
        generate_chapter,
        split_chapter_to_sections,
    )
    from app.services.kb_base_service import resolve_mount_doc_ids

    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    outline = values.get("outline", [])
    is_subsection = "." in chapter_no
    target_no = chapter_no.rsplit(".", 1)[0] if is_subsection else chapter_no
    chapter = next((c for c in outline if str(c.get("chapter_no", "")) == target_no), None)
    if chapter is None:
        raise BizError(code=4004, message=f"章节 {chapter_no} 不在大纲中，无法生成初稿")

    # 挂载配置合并：知识库级 ∪ 文档级（均 None = 项目全量）
    async with async_session_factory() as db:
        doc_ids = await resolve_mount_doc_ids(
            db, values.get("mounted_kb_ids"), values.get("mounted_doc_ids")
        )

    content = await generate_chapter(
        chapter=chapter,
        score_points=values.get("score_points", []),
        tech_requirements=values.get("tech_requirements", []),
        project_id=uuid.UUID(str(project_id)),
        doc_ids=doc_ids,
    )
    if not content:
        raise BizError(code=5001, message="章节初稿生成失败：LLM 返回为空")

    title = chapter.get("title", "")
    summaries = dict(values.get("chapter_summaries", {}))
    summaries[target_no] = {"title": title, "summary": extract_chapter_summary(content)}
    await update_state(
        project_id,
        {"chapters": {target_no: content}, "chapter_summaries": summaries},
    )
    async with async_session_factory() as db:
        await _persist_chapter_content(
            db,
            str(project_id),
            target_no,
            title,
            content,
            status="draft",
            sections_tree=chapter.get("sections", []),
        )
        await db.commit()
    if is_subsection:
        # 返回目标子节片段；切分未命中时降级返回整章（不阻塞编制）
        for sec in split_chapter_to_sections(content, chapter.get("sections", []) or [], target_no):
            if sec["section_id"] == chapter_no:
                return sec["content"]
    return content


async def export_workflow(project_id: uuid.UUID | str) -> dict:
    """导出 Word — 复用图内 export 节点（export_to_word + 落库 + 事件），结果回写 state."""
    snapshot = await get_state(project_id)
    values = dict(snapshot.values or {})
    if not values.get("chapters"):
        raise BizError(code=4005, message="章节尚未生成，无法导出")

    from app.agents.nodes import export_node

    values.setdefault("project_id", str(project_id))
    updates = await export_node(values)
    if updates.get("error"):
        raise BizError(code=5010, message=updates["error"])
    await update_state(project_id, updates)
    return {
        "export_status": updates.get("export_status", "done"),
        "export_storage_key": updates.get("export_storage_key", ""),
    }


# ───────────────────────── 大纲二次编辑草稿 ─────────────────────────


async def save_outline_draft(
    db,
    project_id: uuid.UUID,
    outline: list[dict],
    mounted_doc_ids: list[str] | None = None,
    mounted_kb_ids: list[str] | None = None,
) -> None:
    """保存大纲二次编辑草稿到 proposal_skeletons.draft（行不存在则创建，upsert）.

    draft 结构：{"outline": [...], "mounted_doc_ids": [...], "mounted_kb_ids": [...]}；
    两个挂载列表为字符串列表（None=未设置挂载，保持项目全量检索语义）。
    """
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton:
        skeleton = ProposalSkeleton(project_id=project_id, tree=[])
        db.add(skeleton)
    skeleton.draft = {
        "outline": outline,
        "mounted_doc_ids": mounted_doc_ids,
        "mounted_kb_ids": mounted_kb_ids,
    }
    skeleton.draft_updated_at = datetime.now(UTC)
    await db.flush()


async def get_outline_draft(db, project_id: uuid.UUID) -> dict | None:
    """读取大纲二次编辑草稿；无草稿（或行不存在）返回 None."""
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton or not skeleton.draft:
        return None
    return {
        "outline": skeleton.draft.get("outline", []),
        "mounted_doc_ids": skeleton.draft.get("mounted_doc_ids"),
        "mounted_kb_ids": skeleton.draft.get("mounted_kb_ids"),
        "updated_at": skeleton.draft_updated_at,
    }


async def clear_outline_draft(db, project_id: uuid.UUID) -> None:
    """清除大纲二次编辑草稿（确认成功后调用，幂等）."""
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if skeleton:
        skeleton.draft = None
        skeleton.draft_updated_at = None
        await db.flush()


# ───────────────────────── 成员收集与审阅意见回派（批次 1c 自 api 下沉） ─────────────────────────


async def list_project_member_ids(db, project_id: uuid.UUID) -> list[uuid.UUID]:
    """项目成员 user_id 列表（confirm-outline 用户级推送目标收集）."""
    from sqlalchemy import select

    from app.models.project import ProjectMember

    result = await db.execute(
        select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    )
    return list(result.scalars().all())


async def redispatch_feedback(
    db, project_id: uuid.UUID, feedback: dict[str, str]
) -> tuple[dict[str, str], list[dict]]:
    """审阅意见回派章节/子节负责人（阶段 5）.

    feedback 键支持章级/子节编号或标题匹配（子节编号/标题来自大纲嵌套树）：
    - 命中分工 → assignment 置 rejected + 意见落库
      （assignee 在分工页「我的任务」看到打回可重编）；
    - 子节无分工时降级匹配父章分工；
    - 无分工章节 → 保留原 rewrite 链路。
    返回 (未被回派的剩余 feedback, 待推送的 task_reviewed 事件列表)，
    事件推送由 api 层执行；仅 flush 不 commit（BUG-1：api 层在 resume 前显式提交）。
    """
    if not feedback:
        return {}, []
    from sqlalchemy import select

    from app.models.proposal import ChapterAssignment
    from app.services.chapter_service import numbered_sections

    snapshot = await get_state(project_id)
    outline = (snapshot.values or {}).get("outline", []) or []
    nos: set[str] = set()
    title_to_no: dict[str, str] = {}
    for c in outline:
        no = str(c.get("chapter_no", ""))
        nos.add(no)
        title_to_no[str(c.get("title", ""))] = no
        # 子节编号/标题同样参与匹配（嵌套树推导，与分工编号规则一致）
        for sub_no, sub_title in numbered_sections(c.get("sections", []) or [], no):
            nos.add(sub_no)
            title_to_no.setdefault(sub_title, sub_no)
    remaining: dict[str, str] = {}
    events: list[dict] = []
    for key, comment in feedback.items():
        chapter_no = key if key in nos else title_to_no.get(key, "")
        if not chapter_no:
            remaining[key] = comment
            continue
        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == chapter_no,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment is None and "." in chapter_no:
            # 子节无分工 → 降级回派父章负责人（章级分工覆盖子节）
            parent_no = chapter_no.rsplit(".", 1)[0]
            result = await db.execute(
                select(ChapterAssignment).where(
                    ChapterAssignment.project_id == project_id,
                    ChapterAssignment.chapter_no == parent_no,
                )
            )
            assignment = result.scalar_one_or_none()
        if assignment is None:
            remaining[key] = comment
            continue
        assignment.status = "rejected"
        assignment.review_comment = comment
        assignment.reviewed_at = datetime.now(UTC)
        events.append(
            {
                "type": "task_reviewed",
                "chapter_no": chapter_no,
                "assignee_id": str(assignment.assignee_id),
                "action": "rejected",
            }
        )
    await db.flush()
    return remaining, events


# ───────────────────────── 后台执行 ─────────────────────────


def _track(task: asyncio.Task) -> asyncio.Task:
    """保持后台任务强引用，避免执行中被 GC."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _write_error(project_id: uuid.UUID | str, message: str) -> None:
    try:
        await update_state(project_id, {"error": message})
    except Exception:
        logger.warning("工作流错误状态回写失败", exc_info=True)


async def _run_guarded(project_id: uuid.UUID | str, user_id: uuid.UUID | str) -> dict | None:
    try:
        return await run_workflow(project_id, user_id)
    except Exception as e:
        logger.exception("工作流后台执行失败: project_id=%s", project_id)
        await _write_error(project_id, f"工作流执行失败: {e}")
        return None


async def _resume_guarded(project_id: uuid.UUID | str, resume_value: Any) -> dict | None:
    try:
        return await resume_workflow(project_id, resume_value)
    except Exception as e:
        logger.exception("工作流恢复执行失败: project_id=%s", project_id)
        await _write_error(project_id, f"工作流恢复失败: {e}")
        return None


def start_workflow_in_background(
    project_id: uuid.UUID | str, user_id: uuid.UUID | str
) -> asyncio.Task:
    """后台启动工作流（HITL 节点 interrupt 停下），端点立即返回.

    幂等：同一项目在途时重复启动被拒（4009）；任务结束（含异常）自动释放槽位。
    """
    key = str(project_id)
    if key in _running:
        raise BizError(code=4009, message="工作流已在执行中，请勿重复启动")
    task = _track(asyncio.create_task(_run_guarded(project_id, user_id)))
    _running.add(key)
    task.add_done_callback(lambda _t: _running.discard(key))
    return task


def resume_workflow_in_background(project_id: uuid.UUID | str, resume_value: Any) -> asyncio.Task:
    """后台恢复工作流，端点立即返回."""
    return _track(asyncio.create_task(_resume_guarded(project_id, resume_value)))
