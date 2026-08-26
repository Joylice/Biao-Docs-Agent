"""LLM 页面配置模型 — 单行 upsert，密钥列存 Fernet 密文."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmSetting(Base):
    """llm_settings 表 — LLM 配置页面化（全局单行，upsert）.

    密钥以 Fernet 密文落库（core/crypto，key 由 jwt_secret 派生），
    GET 接口只返回脱敏值，明文不出库。
    """

    __tablename__ = "llm_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deepseek_api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dashscope_api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_api_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    embedding_api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    llm_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
