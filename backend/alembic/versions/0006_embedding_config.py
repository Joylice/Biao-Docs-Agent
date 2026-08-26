"""扩展 llm_settings：embedding 模型名与密钥可页面化配置.

Revision ID: 0006_embedding_config
Revises: 0005_llm_settings
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_embedding_config"
down_revision: str | None = "0018_chapter_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加 embedding_model、embedding_api_key_enc 列."""
    op.add_column("llm_settings", sa.Column("embedding_model", sa.String(256), nullable=True))
    op.add_column("llm_settings", sa.Column("embedding_api_key_enc", sa.String(512), nullable=True))


def downgrade() -> None:
    """回滚."""
    op.drop_column("llm_settings", "embedding_api_key_enc")
    op.drop_column("llm_settings", "embedding_model")
