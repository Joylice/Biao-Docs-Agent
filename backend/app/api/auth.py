"""认证 API 路由.

DB 与业务逻辑委托 auth_service（批次 1b 分层重构）；
本层保留路由/参数校验/审计埋点/显式 commit/响应组装。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.rbac import user_permission_codes
from app.core.response import success
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.services.infra import auth_service

router = APIRouter()


@router.post("/register")
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户注册."""
    user = await auth_service.register_user(db, req.email, req.password, req.display_name)

    # 事务约定（BUG-1）：响应返回前显式提交，确保后续登录/查重立即可见
    await db.commit()

    return success(data=UserOut.model_validate(user).model_dump(mode="json"))


@router.post("/login")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户登录（支持用户名或邮箱）."""
    user = await auth_service.authenticate_user(db, req.username, req.email, req.password)

    # 审计埋点：登录成功（security.md §4）
    await audit.record(db, user.id, "auth.login", target_type="user", target_id=str(user.id))

    # 事务约定（BUG-1）：审计写入随响应前显式提交
    await db.commit()

    access_token, refresh_token = auth_service.issue_token_pair(str(user.id))

    return success(
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump()
    )


@router.post("/refresh")
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """刷新 token — 验证 refresh token（type=refresh）后签发新 access token."""
    user_id = auth_service.verify_refresh_token(req.refresh_token)

    access_token, refresh_token = auth_service.issue_token_pair(str(user_id))

    # 审计埋点：token 刷新（security.md §4，对齐 auth.login 惯例）
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
    user = await auth_service.get_user_by_id(db, user_id)
    data = UserOut.model_validate(user).model_dump(mode="json")
    data["permissions"] = await user_permission_codes(db, user)
    return success(data=data)
