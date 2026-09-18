"""LLM 用量埋点与观测日志（P1-6 拆分自 llm_service.py）.

- 结构化单行观测日志（可 grep/接入采集）；
- llm_usage_log fire-and-forget 落库（独立 session + 5s 超时，写失败不影响主流程）。
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 用量写入后台任务强引用（避免 fire-and-forget 任务被 GC）
_usage_tasks: set[asyncio.Task[Any]] = set()


def usage_fields(response: Any) -> tuple[int | None, int | None, int | None]:
    """结构化解析响应 usage（部分兼容接口无 usage 字段时全 None）.

    返回 (prompt_tokens, completion_tokens, total_tokens)。
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None

    def _int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return (
        _int(getattr(usage, "prompt_tokens", None)),
        _int(getattr(usage, "completion_tokens", None)),
        _int(getattr(usage, "total_tokens", None)),
    )


def usage_summary(response: Any) -> str:
    """提取响应 usage 摘要（部分兼容接口无 usage 字段时返回空串）."""
    if getattr(response, "usage", None) is None:
        return ""
    prompt_tokens, completion_tokens, total_tokens = usage_fields(response)
    return (
        f"prompt_tokens={prompt_tokens if prompt_tokens is not None else '?'} "
        f"completion_tokens={completion_tokens if completion_tokens is not None else '?'} "
        f"total_tokens={total_tokens if total_tokens is not None else '?'}"
    )


def log_llm_call(
    kind: str,
    model: str,
    elapsed_ms: float,
    ok: bool,
    prompt_chars: int,
    usage: str = "",
    error: str = "",
) -> None:
    """LLM 调用观测日志：单行 key=value（可 grep/接入采集），成功 info 失败 warning."""
    base = (
        f"llm_call kind={kind} model={model} ok={'true' if ok else 'false'} "
        f"duration_ms={elapsed_ms:.1f} prompt_chars={prompt_chars}"
    )
    if ok:
        logger.info("%s usage=%s", base, usage)
    else:
        logger.warning("%s error=%s", base, error)


async def _write_usage_row(entry: dict[str, Any]) -> None:
    """llm_usage_log 落库（独立 session，5s 超时兜底）；写失败仅告警不影响主流程."""
    try:
        from app.core.database import async_session_factory
        from app.models.llm_usage_log import LlmUsageLog

        async with asyncio.timeout(5.0):
            async with async_session_factory() as session:
                session.add(LlmUsageLog(**entry))
                await session.commit()
    except Exception:
        logger.warning("llm_usage_log 写入失败（忽略，不影响主流程）", exc_info=True)


def fire_usage_log(entry: dict[str, Any]) -> None:
    """fire-and-forget 调度用量落库（独立任务 + 独立 session，不阻塞主流程）."""
    try:
        task = asyncio.get_running_loop().create_task(_write_usage_row(entry))
        _usage_tasks.add(task)
        task.add_done_callback(_usage_tasks.discard)
    except RuntimeError:  # 无运行中事件循环（极端场景）→ 跳过埋点
        pass


def usage_entry(
    *,
    kind: str,
    model: str,
    stage_key: str | None,
    project_id: str | None,
    ok: bool,
    elapsed_ms: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error: str | None = None,
    agent_id: str | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """构造 llm_usage_log 行数据（project_id 容错解析 UUID，非法置 NULL）.

    S5 归因：agent_id/skill_name 可选落库（全程 nullable，缺省 None 不影响既有调用方）。
    """
    pid: Any = None
    if project_id:
        try:
            import uuid as _uuid

            pid = _uuid.UUID(str(project_id))
        except (ValueError, AttributeError, TypeError):
            pid = None
    return {
        "project_id": pid,
        "stage_key": stage_key,
        "agent_id": agent_id,
        "skill_name": skill_name,
        "kind": kind,
        "model": model,
        "ok": ok,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": int(elapsed_ms),
        "fallback_used": False,
        "error": (error or "")[:512] or None,
    }
