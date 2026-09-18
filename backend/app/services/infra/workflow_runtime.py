"""工作流运行时服务 — LangGraph 编排与 checkpointer 生命周期（对齐 SDD §6）.

分层约定：API 层仅调用本模块，不直接操作 checkpointer / langgraph。

Checkpointer：
- 生产环境使用 AsyncPostgresSaver + 独立 psycopg AsyncConnectionPool
  （不与 app 的 SQLAlchemy AsyncSession 混用），由 app lifespan 初始化/释放；
- thread_id = str(project_id)；
- 测试可通过 set_saver(InMemorySaver()) 注入替代。

Phase 3 拆分：章节内容操作 → workflow_content_service，
大纲草稿 → workflow_outline_service，意见回派 → workflow_feedback_service。
以下保留 re-export 保持向后兼容（API 层 workflow_runtime.xxx 无需改动）.
"""

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from app.agents.graph import compile_workflow, get_async_postgres_saver
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import BizError

# Phase 3 re-exports — 保持 API 层 workflow_runtime.xxx 调用兼容。
# 用 PEP 484 显式再导出写法（`X as X`）：满足 mypy strict 的 no-implicit-reexport，
# 同时让 ruff F401 不再需要 noqa 兜底（本仓曾因 ruff --fix 误删再导出而炸全量测试）。
from app.services.infra.workflow_content_service import (
    export_workflow as export_workflow,
)
from app.services.infra.workflow_content_service import (
    generate_chapter_draft as generate_chapter_draft,
)
from app.services.infra.workflow_content_service import (
    save_section_edit as save_section_edit,
)
from app.services.infra.workflow_content_service import (
    sync_approved_chapter as sync_approved_chapter,
)
from app.services.infra.workflow_feedback_service import (
    list_project_member_ids as list_project_member_ids,
)
from app.services.infra.workflow_feedback_service import (
    redispatch_feedback as redispatch_feedback,
)
from app.services.infra.workflow_outline_service import (
    clear_outline_draft as clear_outline_draft,
)
from app.services.infra.workflow_outline_service import (
    get_outline_draft as get_outline_draft,
)
from app.services.infra.workflow_outline_service import (
    save_outline_draft as save_outline_draft,
)

logger = logging.getLogger(__name__)

# ───────────────────────── checkpointer 生命周期 ─────────────────────────

_saver: Any = None
_pool: Any = None
_background_tasks: set[asyncio.Task[Any]] = set()
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
        # getattr 动态取：AsyncConnectionPool 由上游 aio 模块从 psycopg_pool 间接引入，
        # 不在其显式导出名单内 → mypy strict 会判 attr-defined，但运行时可用。
        from importlib import import_module

        _aio = import_module("langgraph.checkpoint.postgres.aio")

        # 会被 mypy strict 的 no-implicit-reexport 判为 attr-defined（上游未显式导出）。
        pool_cls: type[Any] = _aio.AsyncConnectionPool

        pool = pool_cls(
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


async def recover_running_workflows() -> dict[str, str]:
    """启动期对账（P1-2.1）：修正重启残留的 status=running 记录.

    api 进程重启后内存 _running 清空、在途 asyncio 任务丢失，DB 中
    status=running 成为永久残留（幂等保护 4009 会误拒新启动）。恢复规则：
    - checkpointer 快照有 pending interrupt → waiting（图实际停在 HITL，
      可正常 resume 继续）；
    - 快照 current_phase=done → done；
    - 其他（执行中断途丢失）→ failed + error 提示。
    checkpointer 未初始化时跳过（无快照可依，避免误标失败）。
    返回 {project_id: 最终 status}。
    """
    if _saver is None:
        logger.warning("checkpointer 未初始化，跳过 running 工作流对账")
        return {}
    from sqlalchemy import select

    from app.models.proposal import ProposalWorkflow

    recovered: dict[str, str] = {}
    async with async_session_factory() as db:
        result = await db.execute(
            select(ProposalWorkflow).where(ProposalWorkflow.status == "running")
        )
        rows = result.scalars().all()
        for wf in rows:
            try:
                snapshot = await get_state(wf.project_id)
            except Exception:
                logger.warning(
                    "恢复对账读取快照失败 project_id=%s，标记 failed", wf.project_id, exc_info=True
                )
                wf.status = "failed"
                wf.error = "服务重启导致工作流中断（快照不可读），请重新启动生成"
                recovered[str(wf.project_id)] = "failed"
                continue
            if pending_interrupt(snapshot) is not None:
                wf.status = "waiting"
            elif (snapshot.values or {}).get("current_phase") == "done":
                wf.status = "done"
            else:
                wf.status = "failed"
                wf.error = "服务重启导致工作流中断，请重新启动生成"
            recovered[str(wf.project_id)] = wf.status
        if rows:
            await db.commit()
    if recovered:
        logger.info("启动对账完成，修正 running 残留工作流 %d 条: %s", len(recovered), recovered)
    return recovered


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


def _graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """按当前 checkpointer 编译工作流图."""
    return compile_workflow(checkpointer=get_saver())


def _config(project_id: uuid.UUID | str) -> RunnableConfig:
    """thread_id = project_id（对齐 SDD §6）."""
    return {"configurable": {"thread_id": str(project_id)}}


# ───────────────────────── 阶段模型路由快照（Phase 1） ─────────────────────────


async def _resolve_snapshot(db: Any, project_id: uuid.UUID | str) -> dict[str, dict[str, Any]]:
    """一次读取全部 enabled 路由行，构建 {stage_key: 路由视图} 路由快照.

    视图字段：{model, temperature, max_tokens, timeout, api_base}；
    缺失 stage（无行/未启用/LLM 调用类字段为空）回退旧全局逻辑
    （runtime.resolve_llm_target 的模型与端点）。DB 失败时按能取到的
    部分返回（可能为空 dict），由调用方决定是否携带。
    """
    from sqlalchemy import select

    from app.models.llm_providers import ModelRoute
    from app.services.infra.settings import runtime

    snap: dict[str, dict[str, Any]] = {}
    try:
        result = await db.execute(select(ModelRoute).where(ModelRoute.enabled.is_(True)))
        rows = result.scalars().all()
    except Exception:
        logger.warning("读取模型路由快照失败", exc_info=True)
        rows = []
    for row in rows:
        if row.model and row.stage_key in runtime.STAGE_KEYS:
            snap[row.stage_key] = {
                "model": row.model,
                "temperature": row.temperature,
                "max_tokens": row.max_tokens,
                "timeout": row.timeout,
                "api_base": None,
            }
    missing = [k for k in runtime.STAGE_KEYS if k not in snap]
    if missing:
        # 缺失 stage 回退旧全局逻辑（模型/端点取自 llm_settings / env）
        try:
            model, api_base, _kwargs, _rp = await runtime.resolve_llm_target()
            fallback = {
                "model": model,
                "temperature": None,
                "max_tokens": None,
                "timeout": None,
                "api_base": api_base,
            }
            for k in missing:
                snap[k] = dict(fallback)
        except Exception:
            logger.warning("路由快照缺失阶段回退解析失败", exc_info=True)
    return snap


async def _routes_snapshot_safe(project_id: uuid.UUID | str) -> dict[str, dict[str, Any]] | None:
    """构建路由快照的防御包装：任何失败/超时返回 None（调用方不携带快照字段）.

    mock 模式直接跳过（mock 分支不触碰路由逻辑，保持 E2E mock 确定性）；
    无 DB 环境（单测/InMemorySaver）返回 None，不触碰输入 payload。
    """
    try:
        from app.services.infra.settings.runtime import is_mock_enabled

        if await is_mock_enabled():
            return None
        async with asyncio.timeout(5.0):
            async with async_session_factory() as db:
                return await _resolve_snapshot(db, project_id)
    except Exception:
        logger.warning("routes_snapshot 构建失败，按无快照继续", exc_info=True)
        return None


async def run_workflow(project_id: uuid.UUID | str, user_id: uuid.UUID | str) -> dict[str, Any]:
    """首次执行工作流；遇 HITL interrupt 自动停下并返回当前结果.

    ainvoke input 合并 routes_snapshot（一次解析全部 enabled 路由行；
    构建失败时不携带该字段，节点侧 state.get 走默认，行为不变）。
    """
    input_payload: dict[str, Any] = {"project_id": str(project_id), "user_id": str(user_id)}
    snap = await _routes_snapshot_safe(project_id)
    if snap is not None:
        input_payload["routes_snapshot"] = snap
    return await _graph().ainvoke(
        input_payload,
        _config(project_id),
    )


async def resume_workflow(project_id: uuid.UUID | str, resume_value: Any) -> dict[str, Any]:
    """恢复被 interrupt 的工作流（confirm_score_points / confirm_outline / review）.

    Command(update=...) 写入最新 routes_snapshot（旧 checkpoint 无该字段时
    经 last-value 通道补齐，节点读取不报错）；快照构建失败时不带 update。
    """
    command_kwargs: dict[str, Any] = {"resume": resume_value}
    snap = await _routes_snapshot_safe(project_id)
    if snap is not None:
        command_kwargs["update"] = {"routes_snapshot": snap}
    return await _graph().ainvoke(Command(**command_kwargs), _config(project_id))


async def get_state(project_id: uuid.UUID | str) -> StateSnapshot:
    """读取 thread 最新 checkpoint 快照（StateSnapshot）."""
    return await _graph().aget_state(_config(project_id))


def pending_interrupt(snapshot: Any) -> dict[str, Any] | None:
    """从快照中提取当前挂起的 HITL interrupt payload，无则 None."""
    for task in snapshot.tasks or ():
        interrupts = getattr(task, "interrupts", None)
        if interrupts:
            # task/interrupts 来自 langgraph 运行时对象（Any），此处显式落到声明类型
            payload: dict[str, Any] = interrupts[0].value
            return payload
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


async def get_status_dict(project_id: uuid.UUID | str) -> dict[str, Any]:
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
        "review_comments": values.get("review_comments", []),
        "export_status": values.get("export_status", ""),
        "export_storage_key": values.get("export_storage_key", ""),
        "error": values.get("error", ""),
        "interrupt": pending_interrupt(snapshot),
    }


async def update_state(project_id: uuid.UUID | str, values: dict[str, Any]) -> None:
    """经 checkpointer 更新 thread 状态（如替换大纲、合并章节）."""
    await _graph().aupdate_state(_config(project_id), values)


async def regenerate_outline(project_id: uuid.UUID | str) -> list[dict[str, Any]]:
    """重新生成大纲 — resume confirm_outline 节点（action=regenerate）.

    仅允许 confirm_outline interrupt 挂起时调用（大纲尚未确认）；节点内复用
    generate_outline_node 以最新提示词重新生成并落库，随后再次 interrupt 挂起
    （保留 pending interrupt，前端可继续确认），返回新大纲。
    """
    await ensure_pending_interrupt(project_id, "confirm_outline")

    result = await resume_workflow(project_id, {"action": "regenerate"})
    outline: list[dict[str, Any]] = result.get("outline", [])
    if not outline:
        raise BizError(code=5011, message=result.get("error") or "重新生成大纲失败")
    return outline


# ───────────────────────── 指定节点重跑（Phase 1 T6） ─────────────────────────

# 重跑白名单：仅生成链路节点可重跑；export/confirm*/review 等 HITL/交付节点禁止
RERUN_NODES: tuple[str, ...] = ("retrieve", "write", "consistency_check", "integrate")
# as_node 限制：LangGraph aupdate_state(as_node=前驱) 只能"假装前驱刚执行完"，
# 重跑实际执行的是前驱的后继链（即目标节点及其后继），无法回溯改历史中间产物
RERUN_NODE_PREDECESSORS: dict[str, str] = {
    "retrieve": "confirm_outline",
    "write": "retrieve",
    "consistency_check": "write",
    "integrate": "consistency_check",
}


def _validate_rerun(project_id: uuid.UUID | str, node_name: str) -> None:
    """重跑前置校验：白名单 + 运行中拒绝（BizError 4090 → api 层 409）."""
    if node_name not in RERUN_NODE_PREDECESSORS:
        raise BizError(
            code=4090,
            message=f"节点 {node_name} 不支持重跑（仅支持：{'/'.join(RERUN_NODES)}）",
        )
    if str(project_id) in _running:
        raise BizError(code=4090, message="工作流正在执行中，请等待结束后再重跑")


async def rerun_from_node(
    project_id: uuid.UUID | str,
    node_name: str,
    chapter_no: str | None = None,
) -> dict[str, Any]:
    """从指定节点重跑工作流（白名单见 RERUN_NODES；运行中拒绝 4090）.

    实现：aupdate_state(config, {}, as_node=前驱节点) 后 ainvoke(None)，
    重新执行前驱的后继链（目标节点及其后继）。
    node_name=write 且 chapter_no 非空时，重跑前先经 update_state 清除该章
    相关 chapters/chapter_summaries 条目（merge reducer 无法删除键，故以
    空字符串/空 dict 覆盖，触发该章重新生成）。
    as_node 限制（SDD §6.5）：仅支持重执行该节点及其后继，无法回溯改
    历史中间产物（如重跑 consistency_check 会连带重跑 write 之后全链）。
    """
    _validate_rerun(project_id, node_name)

    if node_name == "write" and chapter_no:
        await update_state(
            project_id,
            {"chapters": {chapter_no: ""}, "chapter_summaries": {chapter_no: {}}},
        )

    as_node = RERUN_NODE_PREDECESSORS[node_name]
    await _graph().aupdate_state(_config(project_id), {}, as_node=as_node)
    return await _graph().ainvoke(None, _config(project_id))


async def _rerun_guarded(
    project_id: uuid.UUID | str, node_name: str, chapter_no: str | None
) -> dict[str, Any] | None:
    try:
        return await rerun_from_node(project_id, node_name, chapter_no)
    except Exception as e:
        logger.exception("节点重跑失败: project_id=%s node=%s", project_id, node_name)
        await _write_error(project_id, f"节点重跑失败: {e}")
        return None


def rerun_from_node_in_background(
    project_id: uuid.UUID | str,
    node_name: str,
    chapter_no: str | None = None,
) -> asyncio.Task[Any]:
    """后台执行节点重跑，端点立即返回（白名单/运行中校验在创建任务前同步完成）."""
    _validate_rerun(project_id, node_name)
    key = str(project_id)
    task = _track(asyncio.create_task(_rerun_guarded(project_id, node_name, chapter_no)))
    _running.add(key)
    task.add_done_callback(lambda _t: _running.discard(key))
    return task


# ───────────────────────── 后台执行 ─────────────────────────


def _track(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """保持后台任务强引用，避免执行中被 GC."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _write_error(project_id: uuid.UUID | str, message: str) -> None:
    try:
        await update_state(project_id, {"error": message})
    except Exception:
        logger.warning("工作流错误状态回写失败", exc_info=True)


async def _run_guarded(
    project_id: uuid.UUID | str, user_id: uuid.UUID | str
) -> dict[str, Any] | None:
    try:
        return await run_workflow(project_id, user_id)
    except Exception as e:
        logger.exception("工作流后台执行失败: project_id=%s", project_id)
        await _write_error(project_id, f"工作流执行失败: {e}")
        return None


async def _resume_guarded(project_id: uuid.UUID | str, resume_value: Any) -> dict[str, Any] | None:
    try:
        return await resume_workflow(project_id, resume_value)
    except Exception as e:
        logger.exception("工作流恢复执行失败: project_id=%s", project_id)
        await _write_error(project_id, f"工作流恢复失败: {e}")
        return None


def start_workflow_in_background(
    project_id: uuid.UUID | str, user_id: uuid.UUID | str
) -> asyncio.Task[Any]:
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


def resume_workflow_in_background(
    project_id: uuid.UUID | str, resume_value: Any
) -> asyncio.Task[Any]:
    """后台恢复工作流，端点立即返回."""
    return _track(asyncio.create_task(_resume_guarded(project_id, resume_value)))
