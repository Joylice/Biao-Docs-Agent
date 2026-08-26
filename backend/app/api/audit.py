"""审计日志查询 API — 三期 S3（admin only，只读；追加式约束，无 DELETE/PUT）."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id
from app.core.response import paginated
from app.services.infra import audit_service

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
    items, total = await audit_service.query_logs(
        db,
        page,
        page_size,
        action=action,
        user_id=user_id,
        project_id=project_id,
        target_type=target_type,
        start=start,
        end=end,
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
