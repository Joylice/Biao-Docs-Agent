"""文档相关 Schema."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentUploadOut(BaseModel):
    """文档上传响应."""

    id: uuid.UUID
    title: str
    doc_type: str
    status: str
    storage_key: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    """文档列表项."""

    id: uuid.UUID
    title: str
    doc_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ScorePointOut(BaseModel):
    """评分点输出."""

    id: uuid.UUID
    clause_no: str
    item: str
    score: float | None
    criteria: str | None
    is_star: bool
    strategy: str | None
    risk_level: str | None
    confirmed: bool

    model_config = {"from_attributes": True}


class ScorePointUpdate(BaseModel):
    """评分点更新（人工编辑 strategy/确认）."""

    strategy: str | None = None
    confirmed: bool | None = None


class TechRequirementOut(BaseModel):
    """技术需求输出."""

    id: uuid.UUID
    seq: int
    description: str
    category: str | None
    is_mandatory: bool

    model_config = {"from_attributes": True}
