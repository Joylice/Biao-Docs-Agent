"""检索参数持久化模型 — Phase 3 从 localStorage 迁移到 DB.

单行配置表（id=1 固定），存储检索引擎相关参数：
recall_top_k / similarity_threshold / hybrid_weight / rerank 配置。
密钥字段 Fernet 加密入库，复用 BID_LLM_CRYPTO_SECRET。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RetrievalConfig(Base):
    """retrieval_configs 表 — 检索参数持久化（全局单行，id=1）.

    - recall_top_k: 向量检索召回数量（5-100）
    - similarity_threshold: 相似度阈值（0-1，低于此值的结果被过滤）
    - hybrid_weight: 混合检索权重（0=纯关键词，1=纯向量，0.7=偏向量）
    - rerank_enabled: 是否启用重排序
    - rerank_model: 重排序模型名称（如 dashscope/gte-rerank）
    - rerank_top_k: 重排后保留的文档数量
    - rerank_api_key_enc: 重排序专用密钥（Fernet 加密，可复用 embedding 密钥）
    """

    __tablename__ = "retrieval_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    recall_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    similarity_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    hybrid_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    rerank_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rerank_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    rerank_api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
