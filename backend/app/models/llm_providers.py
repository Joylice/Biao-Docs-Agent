"""LLM 服务商注册表 — 替代 llm_settings 表的硬编码密钥列.

参照 OpenMAIC provider-neutral routing 设计：每个 provider 独立一行，
支持能力开关（text/embedding/rerank/vision）、自定义端点、Fernet 加密密钥。

向后兼容：llm_settings 表保留为全局 fallback，新表为增量配置。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProviderRegistry(Base):
    """llm_providers 表 — LLM 服务商注册（每行一个 provider）.

    - prefix: 模型路由前缀（如 deepseek/zhipu/dashscope），用于自动匹配密钥
    - api_key_enc: Fernet 加密的 API Key
    - capabilities: text/embedding/rerank/vision 能力开关
    - builtin: 是否内置 provider（内置项不可删除，仅可禁用）
    """

    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_base: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 能力开关
    cap_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cap_embedding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cap_rerank: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cap_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 状态
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 模型列表（逗号分隔，前端展示用）
    models: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ModelRoute(Base):
    """model_routes 表 — 按流水线阶段分配模型（参照 OpenMAIC MODEL_ROUTES）.

    - stage_key: 流水线阶段标识（parse/score/outline/write/validate/consistency/review/export）
    - model: 主模型（格式 provider/model-name）
    - fallback: JSON 数组，fallback 链
    - thinking: 是否启用思考模式
    - temperature / max_tokens / timeout: 阶段级 LLM 参数
    """

    __tablename__ = "model_routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    stage_name: Mapped[str] = mapped_column(String(128), nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fallback: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # JSON array
    thinking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(nullable=True)
    timeout: Mapped[int | None] = mapped_column(nullable=True)
    hint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
