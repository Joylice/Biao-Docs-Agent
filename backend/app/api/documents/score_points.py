"""评分点路由 — 提取结果查询与人工确认（第一轮-2 拆包自 api/documents.py）."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.schemas.document import ScorePointOut, ScorePointUpdate
from app.services.document import document_service
from app.services.project.project_service import _check_project_member

router = APIRouter()


@router.get("/{project_id}/score-points")
async def list_score_points(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """评分点列表."""
    await _check_project_member(db, project_id, user_id)

    items = await document_service.list_score_points(db, project_id)
    items_data = [ScorePointOut.model_validate(sp).model_dump(mode="json") for sp in items]
    return success(data=items_data)


@router.put("/{project_id}/score-points/{sp_id}")
async def update_score_point(
    project_id: uuid.UUID,
    sp_id: uuid.UUID,
    req: ScorePointUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新评分点（人工编辑 strategy 或确认）."""
    await _check_project_member(db, project_id, user_id)

    sp = await document_service.update_score_point(
        db, project_id, sp_id, req.strategy, req.confirmed
    )

    # 事务约定（BUG-1）：确认/策略修改响应前显式提交，后续工作流立即可见
    await db.commit()

    return success(data=ScorePointOut.model_validate(sp).model_dump(mode="json"))


__all__ = ["router"]
