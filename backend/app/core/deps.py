"""认证依赖 — 从请求中提取当前用户 / 管理员校验."""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer()


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


async def get_current_admin_id(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """管理员校验：用户 email 须在 settings.admin_user_ids（逗号分隔）内.

    C-1：User 表无 role 且开放注册，全局 LLM 配置写端点仅允许管理员调用；
    列表为空时拒绝写入并提示配置 BID_ADMIN_USER_IDS（不放宽为任意登录用户）。
    """
    admins = {s.strip().lower() for s in settings.admin_user_ids.split(",") if s.strip()}
    if not admins:
        raise ForbiddenError("未配置管理员账号（BID_ADMIN_USER_IDS）")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.email.lower() not in admins:
        raise ForbiddenError("无权操作：仅管理员可修改全局 LLM 配置")
    return user_id
