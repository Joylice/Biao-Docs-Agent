"""用户管理 Schema（三期 S1：角色细分）."""

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.core.deps import VALID_ROLES


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
