"""LLM 用量日志模型 — llm_usage_log 表（Phase 1 模型路由运行时）.

每次真实 LLM 调用（成功/失败各一行）由 llm_service 异步 fire-and-forget 写入；
写失败仅告警，不影响主流程。GET /usage/summary 按 stage/model 聚合：
调用次数 / 成功率 / token 总量 / 平均延迟。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmUsageLog(Base):
    """llm_usage_log 表 — LLM 调用用量埋点（每行一次调用）.

    - ok: 调用是否成功；失败行 error 记录根因 repr（截断 512）
    - prompt_tokens/completion_tokens/total_tokens: 结构化 usage（取不到置 NULL）
    - fallback_used: 预留 fallback 链路标记（当前恒 false）
    """

    __tablename__ = "llm_usage_log"
    __table_args__ = (
        Index("ix_llm_usage_log_project_created", "project_id", "created_at"),
        Index("ix_llm_usage_log_stage_created", "stage_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
