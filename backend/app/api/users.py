"""用户管理 API 路由（三期 S1：角色细分 member/kb_admin/admin；阶段 A：RBAC 权限点配置）.

仅系统管理员可用（get_current_admin_id / require_permission("system:manage")）；
角色变更留痕审计 user.role_change，权限点配置留痕审计 rbac.update。
安全约束：不返回 password_hash；禁止变更自身角色；至少保留 1 名 admin；
admin 角色不可移除 system:manage（防自我锁死）。
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import ROLE_ADMIN, get_current_admin_id, get_current_user_id
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
from app.core.security import hash_password
from app.models.project import Project
from app.models.user import User
from app.schemas.user import (
    PasswordResetIn,
    RolePermissionsUpdateIn,
    RoleUpdateIn,
    UserCreateIn,
    UserListOut,
    UserUpdateIn,
)

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
    items = [UserListOut.model_validate(u).model_dump(mode="json") for u in result.scalars().all()]
    return paginated(items, total)


@router.get("/users/options")
async def list_user_options(
    _user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量注册用户下拉数据源（登录即可；阶段7 成员选择/建项目选成员）.

    仅返回最小字段（id/email/display_name），不泄露角色以外的敏感信息。
    """
    result = await db.execute(select(User).order_by(User.created_at.asc()).limit(500))
    items = [
        {"id": str(u.id), "email": u.email, "display_name": u.display_name}
        for u in result.scalars().all()
    ]
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
    if target_id == admin_id:
        raise BizError(code=4000, message="不能变更自己的角色")

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    # 最后一名 admin 保护：降级 admin 前确认仍有其他管理员
    if target.role == ROLE_ADMIN and req.role != ROLE_ADMIN:
        count_result = await db.execute(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        admin_count = count_result.scalar_one_or_none() or 0
        if admin_count <= 1:
            raise BizError(code=4000, message="至少需要保留一名管理员")

    old_role = target.role
    target.role = req.role
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
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none() is not None:
        raise BizError(code=4000, message="该邮箱已注册")

    user = User(
        id=uuid.uuid4(),  # 显式生成：列 default 仅 INSERT 时生效，审计/响应需立即可用
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        role=req.role,
        created_at=datetime.now(UTC),
    )
    db.add(user)
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

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    changes: dict[str, dict] = {}
    if req.display_name is not None:
        changes["display_name"] = {"from": target.display_name, "to": req.display_name}
        target.display_name = req.display_name
    if req.role is not None:
        if target_id == admin_id:
            raise BizError(code=4000, message="不能通过编辑变更自己的角色")
        # 最后一名 admin 保护：降级前确认仍有其他管理员
        if target.role == ROLE_ADMIN and req.role != ROLE_ADMIN:
            count_result = await db.execute(
                select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
            )
            if (count_result.scalar_one_or_none() or 0) <= 1:
                raise BizError(code=4000, message="至少需要保留一名管理员")
        changes["role"] = {"from": target.role, "to": req.role}
        target.role = req.role

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
    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise BizError(code=4004, message="用户不存在")

    target.password_hash = hash_password(req.password)
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
    if target_id == admin_id:
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

    if target.role == ROLE_ADMIN:
        count_result = await db.execute(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        if (count_result.scalar_one_or_none() or 0) <= 1:
            raise BizError(code=4000, message="至少需要保留一名管理员")

    detail = {"email": target.email, "role": target.role}
    await db.delete(target)
    await audit.record(
        db,
        admin_id,
        "user.delete",
        target_type="user",
        target_id=str(target_id),
        detail=detail,
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
