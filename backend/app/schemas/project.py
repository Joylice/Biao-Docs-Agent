"""项目相关 Schema."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    """创建项目请求."""

    name: str
    tender_no: str | None = None
    industry: str | None = None


class ProjectOut(BaseModel):
    """项目信息输出."""

    id: uuid.UUID
    name: str
    tender_no: str | None
    industry: str | None
    status: str
    deadline: datetime | None
    owner_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectMemberAdd(BaseModel):
    """添加协作者请求."""

    email: str


class ProjectListOut(BaseModel):
    """项目列表输出."""

    items: list[ProjectOut]
    total: int
