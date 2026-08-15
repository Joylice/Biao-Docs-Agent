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
