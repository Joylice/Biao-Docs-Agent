"""批注编辑时间 + 版本结构化快照（阶段 E5：批注 PUT/DELETE、版本回滚）.

Revision ID: 0016_annotation_edit_version_rollback
Revises: 0015_annotations_versions
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_annotation_edit_version_rollback"
down_revision: str | None = "0015_annotations_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """chapter_annotations 增 updated_at；proposal_versions 增 snapshot_json（回滚数据源）."""
    op.add_column(
        "chapter_annotations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "proposal_versions",
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除两个新增列."""
    op.drop_column("proposal_versions", "snapshot_json")
    op.drop_column("chapter_annotations", "updated_at")
