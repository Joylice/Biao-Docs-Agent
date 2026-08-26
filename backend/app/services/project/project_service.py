"""项目服务层 — CRUD + 成员管理."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ForbiddenError, NotFoundError
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.schemas.project import ProjectCreate


async def create_project(db: AsyncSession, req: ProjectCreate, owner_id: uuid.UUID) -> Project:
    """创建项目（创建者自动成为 owner + 成员；阶段7：member_ids 建项目选成员）."""
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

    # 阶段7：建项目时选择的成员（仅限已注册用户，自动去重 owner）
    member_ids = [mid for mid in dict.fromkeys(req.member_ids or []) if mid != owner_id]
    if member_ids:
        result = await db.execute(select(User).where(User.id.in_(member_ids)))
        users = list(result.scalars().all())
        if len(users) != len(member_ids):
            raise BizError(code=4004, message="所选成员包含未注册用户")
        for user in users:
            db.add(ProjectMember(project_id=project.id, user_id=user.id))

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


async def list_project_members(
    db: AsyncSession, project_id: uuid.UUID, operator_id: uuid.UUID
) -> list[dict[str, Any]]:
    """成员列表（项目成员可见）：owner 恒在首位，含 email/display_name/is_owner/joined_at."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")
    await _check_project_member(db, project_id, operator_id)

    rows_result = await db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
    )
    items = [
        {
            "user_id": member.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "is_owner": member.user_id == project.owner_id,
            "joined_at": member.joined_at,
        }
        for member, user in rows_result.all()
    ]
    # owner 恒在首位，其余按加入时间
    items.sort(key=lambda m: (not m["is_owner"], m["joined_at"]))
    return items


async def remove_project_member(
    db: AsyncSession,
    project_id: uuid.UUID,
    target_user_id: uuid.UUID,
    operator_id: uuid.UUID,
) -> None:
    """移除成员（仅 owner 可执行）."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")
    if project.owner_id != operator_id:
        raise ForbiddenError("仅项目创建者可移除成员")
    if target_user_id == project.owner_id:
        raise BizError(code=4000, message="不能移除项目所有者")
    if target_user_id == operator_id:
        raise BizError(code=4000, message="不能移除自己")

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target_user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise NotFoundError("项目成员")
    await db.delete(member)
    await db.flush()


async def delete_project(
    db: AsyncSession, project_id: uuid.UUID, operator_id: uuid.UUID
) -> Project:
    """删除项目（级联清理全部关联数据）.

    权限：项目 owner 或系统管理员（RBAC system:manage，admin 角色）。
    级联清理：
    - DB：projects 外键 ondelete=CASCADE/SET NULL 自动清理关联表
      （documents/score_points/proposal_*/chapter_assignments 等）
    - MinIO：项目关联文档（doc_type != kb_material，项目级 storage_key）逐个删除对象
    - LangGraph checkpointer：checkpoints/checkpoint_blobs/checkpoint_writes
      按 thread_id=project_id 清理（工作流状态残留）
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")

    # 权限：owner 或系统管理员（admin）
    if project.owner_id != operator_id:
        from app.core.rbac import has_permission
        from app.models.user import User

        user_result = await db.execute(select(User).where(User.id == operator_id))
        user = user_result.scalar_one_or_none()
        is_admin = bool(user) and await has_permission(db, user, "system:manage")
        if not is_admin:
            raise ForbiddenError("仅项目创建者或系统管理员可删除项目")

    # 1. 收集项目关联文档的 MinIO storage_key（仅项目级文档；kb_material 为全局共享不删）
    from app.models.document import Document

    doc_result = await db.execute(
        select(Document).where(
            Document.project_id == project_id, Document.doc_type != "kb_material"
        )
    )
    storage_keys = [doc.storage_key for doc in doc_result.scalars().all() if doc.storage_key]

    # 2. 清理 LangGraph checkpointer（thread_id = project_id）
    await _delete_workflow_checkpoints(db, str(project_id))

    # 3. 删除项目（外键 CASCADE 自动清理关联表）
    await db.delete(project)
    await db.flush()

    # 4. MinIO 对象删除（DB 提交后失败仅告警不阻塞项目删除）
    if storage_keys:
        from contextlib import suppress

        from app.services.document import storage_service

        for key in storage_keys:
            with suppress(Exception):
                storage_service.delete_file(key)
    return project


async def _delete_workflow_checkpoints(db: AsyncSession, thread_id: str) -> None:
    """清理 LangGraph checkpointer 中该 thread（项目）的全部 checkpoint 数据.

    优先走 AsyncPostgresSaver.adelete_thread 官方 API（正确清理 checkpoints /
    checkpoint_blobs / checkpoint_writes 全表）；checkpointer 未初始化时静默跳过。
    """
    try:
        from app.services.infra import workflow_runtime

        saver = workflow_runtime.get_saver()
        if saver is not None and hasattr(saver, "adelete_thread"):
            await saver.adelete_thread(thread_id)
    except Exception:
        pass
