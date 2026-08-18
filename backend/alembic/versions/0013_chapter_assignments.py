"""新建 chapter_assignments 表（方案大纲章节分工协作）.

Revision ID: 0013_chapter_assignments
Revises: 0012_project_member_joined_at
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_chapter_assignments"
down_revision: str | None = "0012_project_member_joined_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新建 chapter_assignments：章节分工与编制状态跟踪."""
    op.create_table(
        "chapter_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_no", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "assignee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        # pending|in_progress|submitted|approved|rejected
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id", "chapter_no", name="uq_chapter_assignments_project_chapter"
        ),
    )


def downgrade() -> None:
    """回滚：删除 chapter_assignments 表."""
    op.drop_table("chapter_assignments")
