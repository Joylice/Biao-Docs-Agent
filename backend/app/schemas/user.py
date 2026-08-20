"""用户管理 Schema（三期 S1：角色细分；阶段 A：RBAC 权限点配置）."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.deps import VALID_ROLES
from app.core.rbac import FUNCTIONAL_PERMISSIONS


class UserListOut(BaseModel):
    """用户列表输出（不含 password_hash）."""

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleUpdateIn(BaseModel):
    """角色变更请求."""

    role: str

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"非法角色: {v}（可选 {sorted(VALID_ROLES)}）")
        return v


class UserCreateIn(BaseModel):
    """管理员创建用户请求（阶段4）."""

    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = "member"

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"非法角色: {v}（可选 {sorted(VALID_ROLES)}）")
        return v


class UserUpdateIn(BaseModel):
    """用户编辑请求（阶段4；至少提供一个字段）."""

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: str | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"非法角色: {v}（可选 {sorted(VALID_ROLES)}）")
        return v


class PasswordResetIn(BaseModel):
    """管理员重置密码请求（阶段4）."""

    password: str = Field(min_length=6, max_length=128)


class RolePermissionsUpdateIn(BaseModel):
    """角色权限点全量覆盖请求（阶段 A；非法/不可授予权限码 422）."""

    codes: list[str]

    @field_validator("codes")
    @classmethod
    def _check_codes(cls, v: list[str]) -> list[str]:
        invalid = set(v) - FUNCTIONAL_PERMISSIONS
        if invalid:
            raise ValueError(f"非法或不可授予的权限码: {sorted(invalid)}")
        return v
