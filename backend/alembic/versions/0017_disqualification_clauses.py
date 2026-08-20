"""废标/红线条款表（阶段 H：废标条款识别）.

Revision ID: 0017_disqualification_clauses
Revises: 0016_annotation_edit_version_rollback
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_disqualification_clauses"
down_revision: str | None = "0016_annotation_edit_version_rollback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新建 disqualification_clauses：parse 提取的废标/红线条款（人工可确认）."""
    op.create_table(
        "disqualification_clauses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("clause_no", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("risk_category", sa.String(30), nullable=False, server_default="other"),
        sa.Column("severity", sa.String(10), nullable=False, server_default="mid"),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_disqualification_clauses_project_id",
        "disqualification_clauses",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_disqualification_clauses_project_id", table_name="disqualification_clauses")
    op.drop_table("disqualification_clauses")
