"""创建 llm_settings 表（LLM 配置页面化，单行 upsert）.

Revision ID: 0005_llm_settings
Revises: 0004_audit_logs
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0005_llm_settings"
down_revision: str | None = "0004_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 llm_settings 表（密钥列存 Fernet 密文）."""
    op.create_table(
        "llm_settings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("deepseek_api_key_enc", sa.String(512), nullable=True),
        sa.Column("dashscope_api_key_enc", sa.String(512), nullable=True),
        sa.Column("embedding_api_base", sa.String(512), nullable=True),
        sa.Column("llm_mock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """回滚."""
    op.drop_table("llm_settings")
