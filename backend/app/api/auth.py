"""认证 API 路由."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError
from app.core.rbac import user_permission_codes
from app.core.response import success
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter()


@router.post("/register")
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户注册."""
    # 检查邮箱是否已注册
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise BizError(code=4000, message="该邮箱已注册")

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # 事务约定（BUG-1）：响应返回前显式提交，确保后续登录/查重立即可见
    await db.commit()

    return success(data=UserOut.model_validate(user).model_dump(mode="json"))


@router.post("/login")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户登录（支持用户名或邮箱）."""
    # 登录标识：优先 username，其次 email（目前用户模型用 email 作为唯一标识，
    # username 字段待后续迁移添加，此处先将 username 作为 email 兼容查询）
    login_identifier = req.username or req.email
    if not login_identifier:
        raise BizError(code=4001, message="请输入用户名或邮箱")

    result = await db.execute(select(User).where(User.email == login_identifier))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise BizError(code=4001, message="用户名或密码错误")

    # 审计埋点：登录成功（security.md §4）
    await audit.record(db, user.id, "auth.login", target_type="user", target_id=str(user.id))

    # 事务约定（BUG-1）：审计写入随响应前显式提交
    await db.commit()

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    return success(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump()
    )


@router.post("/refresh")
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """刷新 token — 验证 refresh token（type=refresh）后签发新 access token."""
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise BizError(code=4001, message="refresh token 无效或已过期")

    access_token = create_access_token(str(payload["sub"]))
    refresh_token = create_refresh_token(str(payload["sub"]))

    # 审计埋点：token 刷新（security.md §4，对齐 auth.login 惯例）
    user_id = uuid.UUID(str(payload["sub"]))
    await audit.record(db, user_id, "auth.refresh", target_type="user", target_id=str(user_id))

    # 事务约定（BUG-1）：审计写入随响应前显式提交
    await db.commit()

    return success(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump()
    )


@router.get("/me")
async def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前用户信息（含权限点列表，前端菜单权限点驱动）."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise BizError(code=4004, message="用户不存在")
    data = UserOut.model_validate(user).model_dump(mode="json")
    data["permissions"] = await user_permission_codes(db, user)
    return success(data=data)
