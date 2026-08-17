"""RBAC 权限体系 — 权限点目录、角色权限解析与校验依赖（迁移 0011_rbac）.

双维模型：功能权限（RBAC：角色 → 权限点，全局）+ 数据范围（项目成员表 / owner 属性，项目内）。
require_permission 只判功能权限；项目内数据范围由 _check_project_member / owner 校验负责。
"""

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import _load_user_or_forbid, get_current_user_id
from app.core.exceptions import ForbiddenError
from app.models.rbac import RolePermission
from app.models.user import User

# 权限点目录（与迁移 0011 种子一致；新增权限点：种子行 + 此处登记）
PERMISSIONS: dict[str, str] = {
    "system:manage": "系统管理（用户/审计/模型设置）",
    "kb:manage": "资料库管理（编辑/删除）",
    "kb:read": "资料库读取（列表/检索）",
    "kb:upload": "资料库上传",
    "settings:read": "LLM 配置读取",
    # project:member_manage 为 owner 数据属性（不走角色表），仅作权限点目录登记
    "project:member_manage": "项目成员管理（owner 数据属性）",
}

PERMISSION_CATEGORIES: dict[str, str] = {
    "system:manage": "system",
    "kb:manage": "kb",
    "kb:read": "kb",
    "kb:upload": "kb",
    "settings:read": "settings",
    "project:member_manage": "project",
}

# 角色 → 权限点缓存（模块级；None=未加载。PUT role / 种子更新后 invalidate_rbac_cache）
_role_permission_cache: dict[str, frozenset[str]] | None = None


def invalidate_rbac_cache() -> None:
    """清空角色权限缓存（角色变更/种子更新后调用）."""
    global _role_permission_cache
    _role_permission_cache = None


async def load_role_permissions(db: AsyncSession) -> dict[str, frozenset[str]]:
    """全量加载角色 → 权限点映射（首次查询后缓存；空映射也缓存）."""
    global _role_permission_cache
    if _role_permission_cache is not None:
        return _role_permission_cache
    result = await db.execute(select(RolePermission))
    mapping: dict[str, set[str]] = {}
    for rp in result.scalars().all():
        mapping.setdefault(rp.role_code, set()).add(rp.permission_code)
    _role_permission_cache = {k: frozenset(v) for k, v in mapping.items()}
    return _role_permission_cache


async def role_permissions(db: AsyncSession, role: str) -> frozenset[str]:
    """角色 → 权限点集合（缓存读；未知角色返回空集）."""
    mapping = await load_role_permissions(db)
    return mapping.get(role, frozenset())


def _whitelist_emails() -> set[str]:
    """BID_ADMIN_USER_IDS 邮箱白名单（小写；过渡期兼容）."""
    return {s.strip().lower() for s in settings.admin_user_ids.split(",") if s.strip()}


async def has_permission(db: AsyncSession, user: User, code: str) -> bool:
    """用户是否具备权限点：白名单命中恒 True；admin 恒含全部功能权限点."""
    if user.email.lower() in _whitelist_emails():
        return True
    if user.role == "admin":
        return True
    return code in await role_permissions(db, user.role)


def require_permission(code: str) -> Callable[..., Awaitable[uuid.UUID]]:
    """FastAPI 依赖工厂：校验当前用户具备指定权限点（否则 403）.

    用法：_perm: uuid.UUID = Depends(require_permission("system:manage"))
    """

    async def _check(
        user_id: uuid.UUID = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        user = await _load_user_or_forbid(db, user_id)
        if not await has_permission(db, user, code):
            raise ForbiddenError(f"无权操作：缺少权限 {code}")
        return user_id

    return _check
