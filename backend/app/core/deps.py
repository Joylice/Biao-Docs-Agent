"""认证依赖 — 从请求中提取当前用户 / 角色校验（三期：users.role 细分）."""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import decode_token
from app.models.project import Project
from app.models.user import User

bearer_scheme = HTTPBearer()

# 三期角色模型：member（默认）/ kb_admin（全局资料库管理）/ admin（系统管理）
ROLE_MEMBER = "member"
ROLE_KB_ADMIN = "kb_admin"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_MEMBER, ROLE_KB_ADMIN, ROLE_ADMIN}


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> uuid.UUID:
    """从 JWT 中提取当前用户 ID."""
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise UnauthorizedError("Token 无效或已过期")
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedError("Token 缺少用户信息")
    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedError("Token 用户 ID 格式错误") from None


def _whitelist_emails() -> set[str]:
    """BID_ADMIN_USER_IDS 邮箱白名单（小写）."""
    return {s.strip().lower() for s in settings.admin_user_ids.split(",") if s.strip()}


async def _load_user_or_forbid(db: AsyncSession, user_id: uuid.UUID) -> User:
    """载入用户；不存在时拒绝（token 有效但用户已删除的边界场景）."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ForbiddenError("无权操作：用户不存在")
    return user


async def _is_admin(db: AsyncSession, user: User) -> bool:
    """系统管理员：具备 system:manage 权限点（RBAC 迁移 0011；白名单兼容在 has_permission 内）."""
    from app.core.rbac import has_permission  # 延迟导入：rbac 顶层依赖本模块，避免循环

    return await has_permission(db, user, "system:manage")


async def _is_kb_admin(db: AsyncSession, user: User) -> bool:
    """资料库管理员：具备 kb:manage 权限点（RBAC 迁移 0011）."""
    from app.core.rbac import has_permission  # 延迟导入：rbac 顶层依赖本模块，避免循环

    return await has_permission(db, user, "kb:manage")


async def get_current_admin_id(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """系统管理员校验（三期：users.role 判定，白名单兼容并存）.

    C-1 沿革：一期无 role 时靠 BID_ADMIN_USER_IDS 邮箱白名单；三期引入
    users.role 后以 role=admin 为准，白名单命中视为 admin（OR 判定）。
    """
    user = await _load_user_or_forbid(db, user_id)
    if not await _is_admin(db, user):
        raise ForbiddenError("无权操作：该操作仅限管理员")
    return user_id


async def get_current_kb_admin_id(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """资料库管理员校验：全局资料删除/编辑等（三期 S1）."""
    user = await _load_user_or_forbid(db, user_id)
    if not await _is_kb_admin(db, user):
        raise ForbiddenError("无权操作：该操作仅限资料库管理员")
    return user_id


async def get_current_owner_id(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """项目所有者校验（owner 数据属性，阶段二成员管理端点）.

    项目内数据范围校验走 service（_check_project_member / owner 判定）；
    本依赖供 API 层快速拦截非 owner，避免进入业务逻辑。
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("项目")
    if project.owner_id != user_id:
        raise ForbiddenError("仅项目创建者可执行该操作")
    return user_id
