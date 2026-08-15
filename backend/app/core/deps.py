"""认证依赖 — 从请求中提取当前用户."""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token

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
