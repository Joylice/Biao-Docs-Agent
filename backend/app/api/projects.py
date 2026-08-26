"""项目管理 API 路由."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.response import paginated, success
from app.schemas.project import ProjectCreate, ProjectMemberAdd, ProjectOut
from app.services.project.project_service import (
    add_project_member,
    create_project,
    delete_project,
    get_project,
    list_project_members,
    list_projects,
    remove_project_member,
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

    # 事务约定（BUG-1）：响应返回前显式提交，新建项目立即可查（不再短暂 404）
    await db.commit()

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

    # 事务约定（BUG-1）：成员 + 审计同事务，响应前显式提交（新成员不再短暂 403）
    await db.commit()

    return success(message="成员添加成功")


@router.get("/{project_id}/members")
async def list_members_api(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """成员列表（项目成员可见；只读不记审计）."""
    items = await list_project_members(db, project_id, user_id)
    return success(data={"items": items})


@router.delete("/{project_id}/members/{target_user_id}")
async def remove_member_api(
    project_id: uuid.UUID,
    target_user_id: uuid.UUID,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """移除成员（仅 owner）."""
    await remove_project_member(db, project_id, target_user_id, owner_id)

    # 审计埋点：项目成员变更（security.md §4）
    await audit.record(
        db,
        owner_id,
        "project.member_remove",
        project_id=project_id,
        target_type="member",
        target_id=str(target_user_id),
    )

    # 事务约定（BUG-1）：成员删除 + 审计同事务，响应前显式提交
    await db.commit()

    return success(message="成员移除成功")


@router.delete("/{project_id}")
async def delete_project_api(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除项目（仅 owner 或系统管理员）：级联清理关联数据 + MinIO + 工作流 checkpoint."""
    # 执行删除（service 内完成权限校验 + 级联清理，返回被删项目供审计）
    project = await delete_project(db, project_id, user_id)

    # 审计埋点：项目删除（security.md §4）；复用 service 返回的项目信息，避免重复查询
    await audit.record(
        db,
        user_id,
        "project.delete",
        project_id=project_id,
        detail={"project_name": project.name},
    )

    # 事务约定（BUG-1）：删除 + 审计同事务，响应前显式提交
    await db.commit()

    return success(message="项目已删除")
