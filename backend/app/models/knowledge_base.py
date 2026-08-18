"""知识库模型 — 多知识库容器（个人/项目/公司三级可见性）."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCOPE_PERSONAL = "personal"
SCOPE_PROJECT = "project"
SCOPE_COMPANY = "company"
VALID_SCOPES = {SCOPE_PERSONAL, SCOPE_PROJECT, SCOPE_COMPANY}


class KnowledgeBase(Base):
    """知识库容器表 — 素材（documents.kb_material）按库分组与授权.

    可见性：company 全员可见；project 限该项目成员；personal 仅 owner 本人。
    """

    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,  # NULL = 个人库 / 公司库（非项目维度）
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,  # NULL = 公司种子库（管理员集体维护）
    )
    scope: Mapped[str] = mapped_column(String(10), nullable=False)  # personal|project|company
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
