"""扩展 llm_settings：embedding 模型名与密钥可页面化配置.

Revision ID: 0006_embedding_config
Revises: 0018_chapter_content
Create Date: 2026-08-24

注: 文件名前缀 0018a 反映其在迁移链中的实际位置（0018 之后）。
revision ID 字符串仍为 "0006_embedding_config"（历史遗留命名），
后续迁移 0019/0020 均引用此 ID，不级联修改以避免链断裂风险。
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
