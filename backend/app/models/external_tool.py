"""外部工具与阶段绑定模型 — Phase 2 Tavily 式外部工具系统.

参照 ProviderRegistry 的 Mapped 风格：每个 ExternalTool 独立一行，
支持 preset 预设（tavily/brave/searxng/custom）、密钥 Fernet 加密、
按 auth_style 注入请求。StageToolBinding 将工具绑定到流水线阶段，
供 registry.get_definitions 动态组装 OpenAI function schema。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExternalTool(Base):
    """external_tools 表 — 外部搜索工具注册（每行一个工具）.

    - name: 工具显示名（如 "Tavily Search"）
    - preset: 预设类型（tavily/brave/searxng/custom），决定 auth_style/response_path
    - tool_type: 工具类型（http_search），预留扩展
    - api_key_enc: Fernet 加密的 API Key（searxng 可为 NULL）
    - base_url: 自定义请求地址（NULL 时取 preset 的 default_base_url）
    - timeout_ms: HTTP 超时毫秒数
    - max_query_chars: 查询字符串最大长度（截断防注入）
    - enabled: 启用开关
    - version: 乐观锁版本号（更新时 WHERE version=expected）
    """

    __tablename__ = "external_tools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    preset: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    tool_type: Mapped[str] = mapped_column(String(32), nullable=False, default="http_search")
    api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    max_query_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=400)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StageToolBinding(Base):
    """stage_tool_bindings 表 — 工具与流水线阶段绑定（多对一）.

    - tool_id: 外部工具 ID（ON DELETE CASCADE）
    - stage_key: 流水线阶段标识（parse/outline/write/validate）
    - 复合主键 (tool_id, stage_key)，同一工具可绑定多个阶段
    """

    __tablename__ = "stage_tool_bindings"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("external_tools.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage_key: Mapped[str] = mapped_column(String(64), primary_key=True)
