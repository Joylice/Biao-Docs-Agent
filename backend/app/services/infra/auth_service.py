"""认证服务 — 注册查重建档 / 登录验证 / refresh 校验 / token 签发 / 当前用户查询.

批次 1b 自 api/auth.py 下沉；密码哈希与 JWT 继续经 app.core.security。
安全约定：登录失败统一 4001「用户名或密码错误」（不泄露账号是否存在）；
refresh 仅接受 type=refresh 的 token。事务约定：写路径只 flush 不 commit，
由 api 层在审计写入后显式提交（BUG-1）。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User


async def register_user(db: AsyncSession, email: str, password: str, display_name: str) -> User:
    """用户注册：邮箱查重（4000）→ 建档（密码哈希）→ flush/refresh，不 commit."""
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise BizError(code=4000, message="该邮箱已注册")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession, username: str | None, email: str | None, password: str
) -> User:
    """登录验证（支持用户名或邮箱）；失败统一 4001.

    登录标识：优先 username，其次 email（目前用户模型用 email 作为唯一标识，
    username 字段待后续迁移添加，此处先将 username 作为 email 兼容查询）。
    """
    login_identifier = username or email
    if not login_identifier:
        raise BizError(code=4001, message="请输入用户名或邮箱")

    result = await db.execute(select(User).where(User.email == login_identifier))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise BizError(code=4001, message="用户名或密码错误")
    return user


def verify_refresh_token(refresh_token: str) -> uuid.UUID:
    """校验 refresh token（type=refresh）并返回 user_id；无效/过期/类型不符 → 4001."""
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise BizError(code=4001, message="refresh token 无效或已过期")
    return uuid.UUID(str(payload["sub"]))


def issue_token_pair(user_id: str) -> tuple[str, str]:
    """签发 (access_token, refresh_token) 对（纯计算，不触 DB）."""
    return create_access_token(user_id), create_refresh_token(user_id)


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    """按 id 取用户，不存在 → 4004（/auth/me 用）."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise BizError(code=4004, message="用户不存在")
    return user
