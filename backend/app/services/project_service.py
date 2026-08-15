"""项目服务层 — CRUD + 成员管理."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ForbiddenError, NotFoundError
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.schemas.project import ProjectCreate


async def create_project(db: AsyncSession, req: ProjectCreate, owner_id: uuid.UUID) -> Project:
    """创建项目（创建者自动成为 owner + 成员）."""
    project = Project(
        name=req.name,
        tender_no=req.tender_no,
        industry=req.industry,
        owner_id=owner_id,
    )
    db.add(project)
    await db.flush()

    # owner 自动加入成员表
    member = ProjectMember(project_id=project.id, user_id=owner_id)
    db.add(member)
    await db.flush()
    await db.refresh(project)
    return project


async def list_projects(
    db: AsyncSession, user_id: uuid.UUID, page: int = 1, page_size: int = 20
) -> tuple[list[Project], int]:
    """列出用户可见的项目（作为 owner 或成员）."""
    # 子查询：用户参与的项目 ID
    member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    # owner 的项目
    base_query = select(Project).where(
        (Project.owner_id == user_id) | (Project.id.in_(member_project_ids))
    )

    # 总数
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页
    items_query = (
        base_query.order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(items_query)
    items = list(result.scalars().all())

    return items, total


async def get_project(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> Project:
    """获取单个项目（校验权限）."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")
    await _check_project_member(db, project_id, user_id)
    return project


async def add_project_member(
    db: AsyncSession, project_id: uuid.UUID, email: str, operator_id: uuid.UUID
) -> None:
    """通过 email 添加协作者."""
    # 校验操作者是 owner
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")
    if project.owner_id != operator_id:
        raise ForbiddenError("仅项目创建者可添加成员")

    # 查找目标用户
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise BizError(code=4004, message=f"用户 {email} 不存在")

    # 检查是否已是成员
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise BizError(code=4000, message="该用户已是项目成员")

    member = ProjectMember(project_id=project_id, user_id=user.id)
    db.add(member)
    await db.flush()


async def _check_project_member(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """校验用户是项目成员."""
    # owner 直接通过
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project and project.owner_id == user_id:
        return

    # 检查成员表
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise ForbiddenError("您不是该项目成员")
