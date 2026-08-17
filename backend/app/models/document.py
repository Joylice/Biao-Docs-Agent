"""文档模型 — 对齐 SDD §4.1."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    """文档表（招标文件/资料/导出物）."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,  # None = 全局共享资料库（kb_material 独立管理）
    )
    doc_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # tender_file|kb_material|export
    title: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)  # MinIO key
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded"
    )  # uploaded|parsing|parsed|confirmed|indexed|failed
    category: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # 三期：素材分类（product_material|history_proposal|qualification|other，NULL=未分类）
    tags: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )  # 三期：自由标签数组（迁移 0008_documents_category_tags）
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScorePoint(Base):
    """评分点表."""

    __tablename__ = "score_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id"),
        nullable=False,
    )
    clause_no: Mapped[str] = mapped_column(Text, nullable=False)
    item: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_star: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    strategy: Mapped[str | None] = mapped_column(Text, nullable=True)  # 人工可编辑
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high|mid|low
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TechRequirement(Base):
    """技术需求清单."""

    __tablename__ = "tech_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 评分点→技术需求梳理映射（迁移 0009）：归属评分点，NULL=通用需求不归属具体评分点
    sp_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("score_points.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 需求来源：sp_derived=由评分点梳理衍生 / tender=招标原文独立提取（NULL=存量旧数据）
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
