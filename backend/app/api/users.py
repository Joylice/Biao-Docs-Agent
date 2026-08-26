"""用户管理 API 路由（三期 S1：角色细分 member/kb_admin/admin；阶段 A：RBAC 权限点配置）.

仅系统管理员可用（get_current_admin_id / require_permission("system:manage")）；
角色变更留痕审计 user.role_change，权限点配置留痕审计 rbac.update。
安全约束：不返回 password_hash；禁止变更自身角色；至少保留 1 名 admin；
admin 角色不可移除 system:manage（防自我锁死）。
DB 操作统一委托 user_service（批次 1a 分层重构）。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id, get_current_user_id
from app.core.exceptions import BizError
from app.core.rbac import (
    PERMISSION_CATEGORIES,
    PERMISSIONS,
    invalidate_rbac_cache,
    require_permission,
    role_permissions,
    set_role_permissions,
)
from app.core.response import paginated, success
from app.schemas.user import (
    PasswordResetIn,
    RolePermissionsUpdateIn,
    RoleUpdateIn,
    UserCreateIn,
    UserListOut,
    UserUpdateIn,
)
from app.services.infra import user_service

router = APIRouter()


@router.get("/users")
async def list_users(
    keyword: str = Query("", description="email/display_name 模糊过滤（不区分大小写）"),
    role: Literal["member", "kb_admin", "admin"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户列表（仅管理员）."""
    users, total = await user_service.list_users(db, keyword, role, page, page_size)
    items = [UserListOut.model_validate(u).model_dump(mode="json") for u in users]
    return paginated(items, total)


@router.get("/users/options")
async def list_user_options(
    _user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量注册用户下拉数据源（登录即可；阶段7 成员选择/建项目选成员）.

    仅返回最小字段（id/email/display_name），不泄露角色以外的敏感信息。
    """
    items = await user_service.list_user_options(db)
    return success(data={"items": items})


@router.put("/users/{target_id}/role")
async def update_user_role(
    target_id: uuid.UUID,
    req: RoleUpdateIn,
    admin_id: uuid.UUID = Depends(get_current_user_id),
    _check: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """授予/变更用户角色（仅管理员）."""
    target, old_role = await user_service.update_role(db, target_id, req.role, admin_id)
    await audit.record(
        db,
        admin_id,
        "user.role_change",
        target_type="user",
        target_id=str(target_id),
        detail={"from": old_role, "to": req.role},
    )
    await db.commit()
    # RBAC 缓存失效：角色映射变更后下次判定重新加载
    invalidate_rbac_cache()
    return success(data=UserListOut.model_validate(target).model_dump(mode="json"))


@router.post("/users")
async def create_user(
    req: UserCreateIn,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建用户（仅管理员；审计 user.create）."""
    user = await user_service.create_user(db, req.email, req.password, req.display_name, req.role)
    await audit.record(
        db,
        admin_id,
        "user.create",
        target_type="user",
        target_id=str(user.id),
        detail={"email": req.email, "role": req.role},
    )
    await db.commit()
    return success(data=UserListOut.model_validate(user).model_dump(mode="json"))


@router.patch("/users/{target_id}")
async def update_user(
    target_id: uuid.UUID,
    req: UserUpdateIn,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑用户 display_name/role（仅管理员；审计 user.update）."""
    if req.display_name is None and req.role is None:
        raise BizError(code=4000, message="没有可更新的字段")

    target, changes = await user_service.update_user(
        db, target_id, req.display_name, req.role, admin_id
    )
    await audit.record(
        db,
        admin_id,
        "user.update",
        target_type="user",
        target_id=str(target_id),
        detail={"changes": changes},
    )
    await db.commit()
    if "role" in changes:
        invalidate_rbac_cache()
    return success(data=UserListOut.model_validate(target).model_dump(mode="json"))


@router.put("/users/{target_id}/password")
async def reset_user_password(
    target_id: uuid.UUID,
    req: PasswordResetIn,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重置用户密码（仅管理员；审计 user.password_reset）."""
    await user_service.reset_password(db, target_id, req.password)
    await audit.record(
        db,
        admin_id,
        "user.password_reset",
        target_type="user",
        target_id=str(target_id),
    )
    await db.commit()
    return success()


@router.delete("/users/{target_id}")
async def delete_user(
    target_id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除用户（仅管理员；审计 user.delete）.

    保护规则：不能删自己；名下有 owner 项目拒绝（需先转移）；至少保留一名 admin。
    """
    target = await user_service.delete_user(db, target_id, admin_id)
    await audit.record(
        db,
        admin_id,
        "user.delete",
        target_type="user",
        target_id=str(target_id),
        detail={"email": target.email, "role": target.role},
    )
    await db.commit()
    invalidate_rbac_cache()
    return success()


@router.get("/rbac/permissions")
async def list_permission_catalog(
    _admin_id: uuid.UUID = Depends(require_permission("system:manage")),
) -> dict:
    """权限点目录（仅系统管理员；阶段 A 权限配置页列头）."""
    items = [
        {"code": code, "name": name, "category": PERMISSION_CATEGORIES[code]}
        for code, name in PERMISSIONS.items()
    ]
    return success(data={"items": items})


@router.get("/rbac/roles/{role}/permissions")
async def get_role_permission_codes(
    role: Literal["member", "kb_admin", "admin"],
    _admin_id: uuid.UUID = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """角色当前权限点映射（仅系统管理员）."""
    codes = sorted(await role_permissions(db, role))
    return success(data={"role": role, "codes": codes})


@router.put("/rbac/roles/{role}/permissions")
async def update_role_permission_codes(
    role: Literal["member", "kb_admin", "admin"],
    req: RolePermissionsUpdateIn,
    admin_id: uuid.UUID = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量覆盖角色权限点（仅系统管理员；审计 rbac.update）.

    admin 角色必须保留 system:manage（防自我锁死）；未知码/owner 数据属性权限码拒绝。
    """
    old_codes = sorted(await role_permissions(db, role))
    await set_role_permissions(db, role, req.codes)
    await audit.record(
        db,
        admin_id,
        "rbac.update",
        target_type="role",
        target_id=role,
        detail={"role": role, "from": old_codes, "to": sorted(req.codes)},
    )
    await db.commit()
    return success(data={"role": role, "codes": sorted(req.codes)})
