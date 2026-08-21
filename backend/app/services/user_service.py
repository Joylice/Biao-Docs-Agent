"""用户管理服务 — 三期 S1/阶段4（用户 CRUD、角色变更、密码重置的 DB 操作）.

安全约束：不返回 password_hash（序列化在 api 层经 UserListOut）；
禁止变更自身角色；至少保留 1 名 admin；删除前校验名下项目。
事务约定：本服务只读/写会话不 commit，由 api 层显式提交（BUG-1）。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import ROLE_ADMIN
from app.core.exceptions import BizError
from app.core.security import hash_password
from app.models.project import Project
from app.models.user import User


async def list_users(
    db: AsyncSession,
    keyword: str = "",
    role: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    """用户列表：keyword 模糊过滤 email/display_name（不区分大小写）+ role 过滤.

    返回 (users, total)；按 created_at 倒序分页。
    """
    query = select(User)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
    if role:
        query = query.where(User.role == role)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    items_query = (
        query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    result = await db.execute(items_query)
    return list(result.scalars().all()), total


async def list_user_options(db: AsyncSession) -> list[dict]:
    """全量注册用户下拉数据源（仅最小字段 id/email/display_name；注册正序，上限 500）."""
    result = await db.execute(select(User).order_by(User.created_at.asc()).limit(500))
    return [
        {"id": str(u.id), "email": u.email, "display_name": u.display_name}
        for u in result.scalars().all()
    ]


async def create_user(
    db: AsyncSession, email: str, password: str, display_name: str, role: str
) -> User:
    """创建用户（邮箱查重；密码哈希经 app.core.security）.

    显式生成 id：列 default 仅 INSERT 时生效，审计/响应需立即可用。
    """
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise BizError(code=4000, message="该邮箱已注册")

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        created_at=datetime.now(UTC),
    )
    db.add(user)
    return user


async def _admin_count(db: AsyncSession) -> int:
    """当前 admin 角色用户数（最后一名 admin 保护用）."""
    count_result = await db.execute(
        select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
    )
    return count_result.scalar_one_or_none() or 0


async def update_role(
    db: AsyncSession, target_id: uuid.UUID, new_role: str, operator_id: uuid.UUID
) -> tuple[User, str]:
    """授予/变更用户角色；返回 (target, old_role) 供审计留痕.

    保护规则：不能变更自己的角色；降级最后一名 admin 拒绝。
    """
    if target_id == operator_id:
        raise BizError(code=4000, message="不能变更自己的角色")

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    # 最后一名 admin 保护：降级 admin 前确认仍有其他管理员
    if target.role == ROLE_ADMIN and new_role != ROLE_ADMIN and await _admin_count(db) <= 1:
        raise BizError(code=4000, message="至少需要保留一名管理员")

    old_role = target.role
    target.role = new_role
    return target, old_role


async def update_user(
    db: AsyncSession,
    target_id: uuid.UUID,
    display_name: str | None,
    role: str | None,
    operator_id: uuid.UUID,
) -> tuple[User, dict]:
    """编辑用户 display_name/role；返回 (target, changes) 供审计留痕.

    保护规则：不能通过编辑变更自己的角色；降级最后一名 admin 拒绝。
    """
    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    changes: dict[str, dict] = {}
    if display_name is not None:
        changes["display_name"] = {"from": target.display_name, "to": display_name}
        target.display_name = display_name
    if role is not None:
        if target_id == operator_id:
            raise BizError(code=4000, message="不能通过编辑变更自己的角色")
        # 最后一名 admin 保护：降级前确认仍有其他管理员
        if target.role == ROLE_ADMIN and role != ROLE_ADMIN and await _admin_count(db) <= 1:
            raise BizError(code=4000, message="至少需要保留一名管理员")
        changes["role"] = {"from": target.role, "to": role}
        target.role = role
    return target, changes


async def reset_password(db: AsyncSession, target_id: uuid.UUID, password: str) -> User:
    """重置用户密码（哈希经 app.core.security）."""
    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    target.password_hash = hash_password(password)
    return target


async def delete_user(db: AsyncSession, target_id: uuid.UUID, operator_id: uuid.UUID) -> User:
    """删除用户；返回被删用户供审计留痕.

    保护规则：不能删自己；名下有 owner 项目拒绝（需先转移）；至少保留一名 admin。
    """
    if target_id == operator_id:
        raise BizError(code=4000, message="不能删除自己")

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    owner_count_result = await db.execute(
        select(func.count()).select_from(Project).where(Project.owner_id == target_id)
    )
    if (owner_count_result.scalar_one_or_none() or 0) > 0:
        raise BizError(code=4000, message="该用户名下存在项目，请先转移项目负责人后再删除")

    if target.role == ROLE_ADMIN and await _admin_count(db) <= 1:
        raise BizError(code=4000, message="至少需要保留一名管理员")

    await db.delete(target)
    return target
