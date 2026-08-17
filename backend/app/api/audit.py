"""审计日志查询 API — 三期 S3（admin only，只读；追加式约束，无 DELETE/PUT）."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id
from app.core.response import paginated
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None, description="action 前缀匹配，如 kb."),
    user_id: uuid.UUID | None = Query(None, description="操作人过滤"),
    project_id: uuid.UUID | None = Query(None, description="项目过滤"),
    target_type: str | None = Query(None, description="对象类型精确匹配"),
    start: datetime | None = Query(None, description="起始时间（created_at >=）"),
    end: datetime | None = Query(None, description="截止时间（created_at <=）"),
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审计日志查询（仅管理员；按 created_at 倒序分页；LEFT JOIN 操作人姓名）."""
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

    # 查询行为自身留痕（detail 记录过滤条件，敏感键由 _sanitize 兜底）
    await audit.record(
        db,
        admin_id,
        "audit.query",
        detail={
            "action": action,
            "user_id": str(user_id) if user_id else None,
            "project_id": str(project_id) if project_id else None,
            "target_type": target_type,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "page": page,
        },
    )
    await db.commit()
    return paginated(items, total)
