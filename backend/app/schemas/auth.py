"""认证相关 Schema."""

import uuid

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    """注册请求."""

    email: EmailStr
    password: str
    display_name: str


class LoginRequest(BaseModel):
    """登录请求."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token 响应."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """用户信息输出."""

    id: uuid.UUID
    email: str
    display_name: str

    model_config = {"from_attributes": True}
