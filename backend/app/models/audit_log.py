"""审计日志模型 — 对齐 docs/agents/security.md §4（追加式，禁止更新删除）."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """audit_logs 表 — 关键操作留痕（who/what/when），追加式无软删."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # 如 auth.login
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 对象类型
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 对象标识
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 附加信息（已脱敏）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
