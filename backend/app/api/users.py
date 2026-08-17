"""用户管理 API 路由（三期 S1：角色细分 member/kb_admin/admin）.

仅系统管理员可用（get_current_admin_id）；角色变更留痕审计 user.role_change。
安全约束：不返回 password_hash；禁止变更自身角色；至少保留 1 名 admin。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import ROLE_ADMIN, get_current_admin_id, get_current_user_id
from app.core.exceptions import BizError
from app.core.rbac import invalidate_rbac_cache
from app.core.response import paginated, success
from app.models.user import User
from app.schemas.user import RoleUpdateIn, UserListOut

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
