"""审计日志查询服务 — 三期 S3（列表查询/分页/计数；写入留痕走 app.core.audit）."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


async def query_logs(
    db: AsyncSession,
    page: int,
    page_size: int,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[list[dict], int]:
    """审计日志查询：过滤条件下推 SQL，按 created_at 倒序分页，LEFT JOIN 操作人姓名.

    返回 (items, total)；items 为序列化 dict（用户已删除时 user_name 空串）。
    """
    query = select(AuditLog, User.display_name).join(
        User, AuditLog.user_id == User.id, isouter=True
    )
    if action:
        query = query.where(AuditLog.action.startswith(action))
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if project_id:
        query = query.where(AuditLog.project_id == project_id)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if start:
        query = query.where(AuditLog.created_at >= start)
    if end:
        query = query.where(AuditLog.created_at <= end)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = []
    for log, user_name in result.all():
        items.append(
            {
                "id": str(log.id),
                "user_id": str(log.user_id),
                "user_name": user_name or "",  # 用户已删除（JOIN 未命中）时空串
                "action": log.action,
                "project_id": str(log.project_id) if log.project_id else None,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "detail": log.detail,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
        )
    return items, total
