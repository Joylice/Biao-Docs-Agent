"""项目管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import paginated, success
from app.schemas.project import ProjectCreate, ProjectMemberAdd, ProjectOut
from app.services.project_service import (
    add_project_member,
    create_project,
    get_project,
    list_projects,
)

router = APIRouter()


@router.post("")
async def create_project_api(
    req: ProjectCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建项目."""
    project = await create_project(db, req, user_id)
    return success(data=ProjectOut.model_validate(project).model_dump(mode="json"))


@router.get("")
async def list_projects_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """项目列表."""
    items, total = await list_projects(db, user_id, page, page_size)
    items_data = [ProjectOut.model_validate(p).model_dump(mode="json") for p in items]
    return paginated(items_data, total)


@router.get("/{project_id}")
async def get_project_api(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取项目详情."""
    project = await get_project(db, project_id, user_id)
    return success(data=ProjectOut.model_validate(project).model_dump(mode="json"))


@router.post("/{project_id}/members")
async def add_member_api(
    project_id: uuid.UUID,
    req: ProjectMemberAdd,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """添加协作者."""
    await add_project_member(db, project_id, req.email, user_id)

    # 审计埋点：项目成员变更（security.md §4）
    await audit.record(
        db,
        user_id,
        "project.member_add",
        project_id=project_id,
        target_type="member",
        target_id=req.email,
    )

    return success(message="成员添加成功")
