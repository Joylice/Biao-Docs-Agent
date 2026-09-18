"""章节批注表 + 方案版本库（阶段 4/6）.

Revision ID: 0015_annotations_versions
Revises: 0014_knowledge_bases
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_annotations_versions"
down_revision: str | None = "0014_knowledge_bases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新建 chapter_annotations（章节级留言）与 proposal_versions（方案版本库）."""
    op.create_table(
        "chapter_annotations",
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
        sa.Column("chapter_no", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chapter_annotations_project_chapter",
        "chapter_annotations",
        ["project_id", "chapter_no"],
    )

    op.create_table(
        "proposal_versions",
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_note", sa.Text(), nullable=True),
        sa.Column("storage_key_docx", sa.Text(), nullable=False),
        sa.Column("storage_key_source", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,  # NULL = 自动快照（系统触发）
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "version", name="uq_proposal_versions_project_version"),
    )


def downgrade() -> None:
    """回滚：删除两张新表."""
    op.drop_table("proposal_versions")
    op.drop_index("ix_chapter_annotations_project_chapter", table_name="chapter_annotations")
    op.drop_table("chapter_annotations")
