"""Proposal 系列模型（骨架/章节/审阅/工作流）— 对齐 SDD §4.1."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProposalWorkflow(Base):
    """工作流元数据表 — 每项目一条，记录 LangGraph 执行状态."""

    __tablename__ = "proposal_workflows"
    __table_args__ = (UniqueConstraint("project_id", name="uq_proposal_workflows_project"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # init|parse|confirm|outline|generate|review|export|done
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="init")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # idle|running|waiting|done|failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProposalSkeleton(Base):
    """方案骨架表 — 章节树 JSON."""

    __tablename__ = "proposal_skeletons"
    __table_args__ = (UniqueConstraint("project_id", name="uq_proposal_skeletons_project"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # [{chapter_no,title,sections}]  （sections 可为 string[] 或二次编辑的嵌套树 {title,children}）
    tree: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 大纲二次编辑草稿（确认前防丢失；确认成功后清空）：{"outline": [...], "mounted_doc_ids": [...]}
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    draft_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProposalSection(Base):
    """方案章节表."""

    __tablename__ = "proposal_sections"
    __table_args__ = (
        UniqueConstraint("project_id", "section_id", name="uq_proposal_sections_project_section"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_id: Mapped[str] = mapped_column(String(32), nullable=False)  # 骨架章节号
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # draft|generating|review|approved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # [{chunk_id,doc_title,page_no}]
    citations: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Review(Base):
    """审阅反馈表."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_id: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # approve|edit|rewrite
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 修改后正文或修改意见
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChapterAssignment(Base):
    """章节分工表 — 编制分工与状态跟踪（正文仍存 workflow state/proposal_sections）."""

    __tablename__ = "chapter_assignments"
    __table_args__ = (
        UniqueConstraint("project_id", "chapter_no", name="uq_chapter_assignments_project_chapter"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_no: Mapped[str] = mapped_column(String(32), nullable=False)  # 骨架章节号
    title: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # pending(已分配待接收)|in_progress(编制中)|submitted(已提交待审)|approved(通过)|rejected(打回)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 章节正文（Markdown 源，章节内容读写端点落库；迁移 0018）
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # 富文本编辑器 HTML（与 Markdown 源并存储；可空，迁移 0018）
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChapterAnnotation(Base):
    """章节批注表 — 章节级留言列表（与审核打回意见并存）."""

    __tablename__ = "chapter_annotations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_no: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProposalVersion(Base):
    """方案版本库 — 评审通过后快照 Word + Markdown 源（可下载/归档公司库）."""

    __tablename__ = "proposal_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_proposal_versions_project_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key_docx: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key_source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,  # NULL = 自动快照
    )
    # 结构化快照 {"outline": [...], "chapters": {...}}（阶段 E5 回滚数据源；旧版本为 NULL）
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
