"""认证相关 Schema."""

import uuid

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    """注册请求."""

    email: EmailStr
    password: str
    display_name: str


class LoginRequest(BaseModel):
    """登录请求（支持用户名或邮箱）."""

    username: str | None = None  # 用户名（优先）
    email: EmailStr | None = None  # 邮箱（兼容旧版）
    password: str


class TokenResponse(BaseModel):
    """Token 响应."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """刷新 token 请求."""

    refresh_token: str


class UserOut(BaseModel):
    """用户信息输出."""

    id: uuid.UUID
    email: str
    display_name: str
    role: str = "member"  # 三期：前端按角色渲染管理入口

    @field_validator("role", mode="before")
    @classmethod
    def _role_default(cls, v: str | None) -> str:
        # INSERT default 在 flush 后才生效，未持久化对象 role 为 None → 按默认 member
        return v or "member"

    model_config = {"from_attributes": True}
