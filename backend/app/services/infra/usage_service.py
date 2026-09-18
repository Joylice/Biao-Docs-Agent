"""LLM 用量汇总服务 — llm_usage_log 按 stage/model 聚合（Phase 1 T4）.

聚合口径：调用次数 / 成功率 / token 总量 / 平均延迟；
过滤：project_id、stage_key 可选，时间窗口 days（默认 7 天）。

usage_trend 为配置中心「各智能体 Token 用量趋势」折线图提供数据源，
按 (日期, stage_key) 聚合，日期轴连续补零以对齐多系列折线。
"""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage_log import LlmUsageLog

DEFAULT_DAYS = 7


async def usage_summary(
    db: AsyncSession,
    project_id: UUID | str | None = None,
    stage_key: str | None = None,
    days: int = DEFAULT_DAYS,
) -> list[dict[str, Any]]:
    """按 (stage_key, model) 聚合用量：次数/成功率/token 总量/平均延迟.

    - 时间窗口：created_at >= now - days 天（days<=0 时取全部历史）
    - project_id / stage_key 可选过滤
    - 返回按调用次数降序的字典列表（结构化 rows，供 api 层直出）
    """
    stmt = select(
        LlmUsageLog.stage_key,
        LlmUsageLog.model,
        func.count().label("calls"),
        func.sum(case((LlmUsageLog.ok.is_(True), 1), else_=0)).label("ok_calls"),
        func.coalesce(func.sum(func.coalesce(LlmUsageLog.total_tokens, 0)), 0).label(
            "total_tokens"
        ),
        func.coalesce(func.avg(LlmUsageLog.latency_ms), 0.0).label("avg_latency_ms"),
    )
    if days and days > 0:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = stmt.where(LlmUsageLog.created_at >= since)
    if project_id is not None:
        stmt = stmt.where(LlmUsageLog.project_id == project_id)
    if stage_key:
        stmt = stmt.where(LlmUsageLog.stage_key == stage_key)
    stmt = stmt.group_by(LlmUsageLog.stage_key, LlmUsageLog.model).order_by(func.count().desc())

    result = await db.execute(stmt)
    rows = result.all()
    items: list[dict[str, Any]] = []
    for row in rows:
        calls = int(row.calls or 0)
        ok_calls = int(row.ok_calls or 0)
        items.append(
            {
                "stage_key": row.stage_key,
                "model": row.model,
                "calls": calls,
                "ok_calls": ok_calls,
                "success_rate": round(ok_calls / calls, 4) if calls else 0.0,
                "total_tokens": int(row.total_tokens or 0),
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            }
        )
    return items


async def skill_profiles(
    db: AsyncSession,
    project_id: UUID | str | None = None,
    days: int = DEFAULT_DAYS,
) -> list[dict[str, Any]]:
    """按 skill_name 聚合用量（S5）：次数/成功率/失败数/回退数/token/平均延迟.

    - failed_calls = calls - ok_calls（既有判据：0 token ≠ 没调用，失败行也占位）；
    - skill_name 为 NULL 的历史行（迁移 0032 之前）归入 "unknown"，不丢数据；
    - fallback_used 恒 false 的当前实现下 fallback_calls 恒 0，列保留以防口径漂移；
    - 按 calls 降序。
    """
    stmt = select(
        LlmUsageLog.skill_name,
        func.count().label("calls"),
        func.sum(case((LlmUsageLog.ok.is_(True), 1), else_=0)).label("ok_calls"),
        func.sum(case((LlmUsageLog.fallback_used.is_(True), 1), else_=0)).label("fallback_count"),
        func.coalesce(func.sum(func.coalesce(LlmUsageLog.total_tokens, 0)), 0).label(
            "total_tokens"
        ),
        func.coalesce(func.avg(LlmUsageLog.latency_ms), 0.0).label("avg_latency_ms"),
    )
    if days and days > 0:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = stmt.where(LlmUsageLog.created_at >= since)
    if project_id is not None:
        stmt = stmt.where(LlmUsageLog.project_id == project_id)
    stmt = stmt.group_by(LlmUsageLog.skill_name).order_by(func.count().desc())

    result = await db.execute(stmt)
    items: list[dict[str, Any]] = []
    for row in result.all():
        calls = int(row.calls or 0)
        ok_calls = int(row.ok_calls or 0)
        items.append(
            {
                "skill_name": row.skill_name or "unknown",
                "calls": calls,
                "ok_calls": ok_calls,
                "failed_calls": calls - ok_calls,
                "fallback_calls": int(row.fallback_count or 0),
                "success_rate": round(ok_calls / calls, 4) if calls else 0.0,
                "total_tokens": int(row.total_tokens or 0),
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            }
        )
    return items


async def usage_trend(
    db: AsyncSession,
    project_id: UUID | str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """按 (日期, stage_key) 聚合 token 用量，产出折线图时序结构.

    - dates：窗口内连续日期（ISO 升序，无调用日补零），长度 == days
    - series：每个 stage_key 一条折线，points 与 dates 等长对齐（单位 token）
    - stage_key 为 NULL 的历史行归入 "unknown"
    - 系列按 token 总量降序，前端可据此分配线序与图例顺序

    days <= 0 视为 1 天（趋势图必须锚定窗口，不做全历史展开）。
    """
    span = max(1, days)
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=span - 1)
    dates = [(start_date + timedelta(days=offset)).isoformat() for offset in range(span)]
    index_of = {day: idx for idx, day in enumerate(dates)}

    day_col = func.date(LlmUsageLog.created_at)
    stmt = (
        select(
            day_col.label("day"),
            LlmUsageLog.stage_key,
            func.count().label("calls"),
            func.coalesce(func.sum(func.coalesce(LlmUsageLog.total_tokens, 0)), 0).label(
                "total_tokens"
            ),
        )
        .where(LlmUsageLog.created_at >= datetime.combine(start_date, time.min, tzinfo=UTC))
        .group_by(day_col, LlmUsageLog.stage_key)
    )
    if project_id is not None:
        stmt = stmt.where(LlmUsageLog.project_id == project_id)

    result = await db.execute(stmt)

    buckets: dict[str, dict[str, Any]] = {}
    for row in result.all():
        day_value = row.day
        day_text = day_value.isoformat() if hasattr(day_value, "isoformat") else str(day_value)
        pos = index_of.get(day_text)
        if pos is None:
            continue
        key = row.stage_key or "unknown"
        bucket = buckets.setdefault(key, {"calls": 0, "total_tokens": 0, "points": [0] * span})
        row_calls = int(row.calls or 0)
        row_tokens = int(row.total_tokens or 0)
        bucket["calls"] += row_calls
        bucket["total_tokens"] += row_tokens
        bucket["points"][pos] += row_tokens

    series = [
        {
            "stage_key": key,
            "calls": bucket["calls"],
            "total_tokens": bucket["total_tokens"],
            "points": bucket["points"],
        }
        for key, bucket in sorted(
            buckets.items(),
            # 主序 token 总量，次序调用次数（全零 token 的系列按活跃度排前，避免图例顺序随机）
            key=lambda kv: (kv[1]["total_tokens"], kv[1]["calls"]),
            reverse=True,
        )
    ]
    return {"days": span, "dates": dates, "series": series}
