"""技术需求梳理 API 路由（评分点确认 → 技术需求梳理与映射）."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.schemas.document import RequirementsGenerateIn
from app.services import requirements_service
from app.services.project_service import _check_project_member

router = APIRouter()


@router.post("/{project_id}/requirements/generate")
async def generate_requirements(
    project_id: uuid.UUID,
    req: RequirementsGenerateIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """基于已确认评分点梳理技术需求（LLM），写入 tech_requirements 并回填映射.

    - score_point_ids 省略/null：取该项目全部 confirmed=true 的评分点
    - 显式传列表：用指定评分点（前端"勾选再梳理"）
    - 幂等：同项目重复梳理先删旧 sp_derived 衍生需求再重建
    """
    await _check_project_member(db, project_id, user_id)

    data = await requirements_service.generate_requirements(
        db, project_id, score_point_ids=req.score_point_ids
    )

    # 审计埋点：技术需求梳理（security.md §4）
    await audit.record(
        db,
        user_id,
        "requirements.generate",
        project_id=project_id,
        detail={"total": data["total"], "mapped": data["mapped"]},
    )
    await db.commit()

    return success(data=data)


@router.get("/{project_id}/requirements")
async def list_requirements(
    project_id: uuid.UUID,
    only_mapped: bool = Query(False, description="仅返回已映射评分点的需求"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """技术需求列表（携带 related_sp 映射信息，供前端分组展示）."""
    await _check_project_member(db, project_id, user_id)

    items = await requirements_service.list_requirements(db, project_id, only_mapped=only_mapped)
    return success(data=items)
