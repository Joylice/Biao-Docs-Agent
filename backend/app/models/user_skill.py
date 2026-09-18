"""用户级 Skill 模型 — SKILL.md 契约体系的用户侧存储.

SKILL.md 契约体系的**用户层真源**：内置层走文件系统（`backend/skills/*/SKILL.md`），
用户层走本表。两层在 `skills.registry.list_skills` 合并，**同名时用户层覆盖内置层**。

设计要点：
- ``name`` = 契约 id（对应 SKILL.md frontmatter 的 `name`），与内置层同名即「覆盖内置」；
- ``body_md`` = 行为指令正文（对应 SKILL.md 的 body）；
- ``metadata_json`` = 扩展元信息（data_sections / token_budget / output_fields）；
- ``enabled=False`` 时视为「不存在」⇒ 回退内置层（LLM 自建的 skill 默认 False 待人审）；
- ``created_by`` 记录来源（``llm`` / ``user``）—— 出问题时归因的关键；
- ``owner_id`` = **创建者标记**（不是隔离键）：按产品口径「用户层全员共享」，
  `list_skills` 不做 owner 过滤；保留该列是为审计与未来可能的隔离需求。
- ``version`` = 乐观锁版本号（对齐 ExternalTool 范式），更新时 `WHERE version=expected`。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserSkill(Base):
    """user_skills 表 — 用户自定义 skill（每行一个）."""

    __tablename__ = "user_skills"
    __table_args__ = (
        # 同一 name 全局唯一（用户层内）—— 与内置层同名即「覆盖内置」
        UniqueConstraint("name", name="uq_user_skills_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 创建者（非隔离键；用户层全员共享，见模块 docstring）
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skill_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    stage_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 来源：llm（模型自建，默认 enabled=False 待人审）/ user（人工创建）
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    # 乐观锁（对齐 external_tools.version）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
