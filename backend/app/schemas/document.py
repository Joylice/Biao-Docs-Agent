"""文档相关 Schema."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# 三期 S2：素材分类枚举（NULL/空 = 未分类）
MATERIAL_CATEGORIES = {
    "product_material",  # 产品资料
    "history_proposal",  # 历史方案
    "qualification",  # 资质证书
    "other",  # 其他
}
MAX_TAGS = 10
MAX_TAG_LEN = 20


def validate_category(value: str | None) -> str | None:
    """分类枚举校验（空/None = 未分类）."""
    if value in (None, ""):
        return None
    if value not in MATERIAL_CATEGORIES:
        raise ValueError(f"非法分类: {value}（可选 {sorted(MATERIAL_CATEGORIES)}）")
    return value


def validate_tags(value: list | None) -> list:
    """标签校验：去空白、去重、上限 MAX_TAGS 个、每个 ≤ MAX_TAG_LEN 字符."""
    tags = [t.strip() for t in (value or []) if t and t.strip()]
    if len(tags) > MAX_TAGS:
        raise ValueError(f"标签最多 {MAX_TAGS} 个")
    for t in tags:
        if len(t) > MAX_TAG_LEN:
            raise ValueError(f"标签过长（≤{MAX_TAG_LEN} 字符）: {t}")
    return list(dict.fromkeys(tags))


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
    # 三期 S2：素材分类/标签/上传者（项目文档列表无 uploader_name 属性时兼容默认值）
    category: str | None = None
    tags: list = Field(default_factory=list)
    uploader_name: str = ""

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_default(cls, v: list | None) -> list:
        # INSERT/server default 在 flush 后才生效，未持久化对象 tags 为 None → 空列表
        return v if v is not None else []

    model_config = {"from_attributes": True}


class MaterialUpdateIn(BaseModel):
    """全局素材编辑请求（三期 S2：title/category/tags，均可选）."""

    title: str | None = None
    category: str | None = None
    tags: list | None = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str | None) -> str | None:
        return validate_category(v)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list | None) -> list | None:
        return validate_tags(v) if v is not None else None


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


class RequirementsGenerateIn(BaseModel):
    """技术需求梳理请求：score_point_ids 省略/null → 取全部已确认评分点."""

    score_point_ids: list[uuid.UUID] | None = None
