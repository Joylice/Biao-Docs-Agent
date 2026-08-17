"""documents 表新增 category/tags 列（三期 S2：素材分类与标签）.

Revision ID: 0008_documents_category_tags
Revises: 0007_users_role
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_documents_category_tags"
down_revision: str | None = "0007_users_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 category（单选分类，可空=未分类）与 tags（自由标签数组，默认空）."""
    op.add_column("documents", sa.Column("category", sa.String(30), nullable=True))
    op.add_column(
        "documents",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    """回滚：删除两列."""
    op.drop_column("documents", "tags")
    op.drop_column("documents", "category")
