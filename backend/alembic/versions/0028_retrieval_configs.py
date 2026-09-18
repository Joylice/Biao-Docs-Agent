"""检索参数持久化表 — Phase 3 检索参数从 localStorage 迁移到 DB.

- retrieval_configs: 单行配置表（id=1 固定），存储 recall_top_k、
  similarity_threshold、hybrid_weight、rerank_enabled、rerank_model、
  rerank_top_k、rerank_api_key_enc 等检索相关参数。
- 密钥字段 Fernet 加密入库（复用 BID_LLM_CRYPTO_SECRET）。
- 初次部署时为空，前端优先读 DB，回退 localStorage（向后兼容）。

Revision ID: 0028_retrieval_configs
Revises: 0027_external_tools
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_retrieval_configs"
down_revision: str | None = "0027_external_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 retrieval_configs 表并插入默认行."""
    op.create_table(
        "retrieval_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("recall_top_k", sa.Integer, nullable=False, server_default=sa.text("20")),
        sa.Column("similarity_threshold", sa.Float, nullable=False, server_default=sa.text("0.35")),
        sa.Column("hybrid_weight", sa.Float, nullable=False, server_default=sa.text("0.7")),
        sa.Column("rerank_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("rerank_model", sa.String(128), nullable=True),
        sa.Column("rerank_top_k", sa.Integer, nullable=False, server_default=sa.text("5")),
        sa.Column("rerank_api_key_enc", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 插入默认配置行（id=1）
    op.execute(
        sa.text(
            "INSERT INTO retrieval_configs (id, recall_top_k, similarity_threshold, "
            "hybrid_weight, rerank_enabled, rerank_model, rerank_top_k) "
            "VALUES (1, 20, 0.35, 0.7, true, 'dashscope/gte-rerank', 5)"
        )
    )


def downgrade() -> None:
    """回滚：删除 retrieval_configs 表."""
    op.drop_table("retrieval_configs")
