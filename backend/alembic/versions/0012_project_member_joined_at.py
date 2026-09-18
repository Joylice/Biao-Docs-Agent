"""project_members 增加 joined_at 列（成员加入时间，阶段二成员管理）.

Revision ID: 0012_project_member_joined_at
Revises: 0011_rbac
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_project_member_joined_at"
down_revision: str | None = "0011_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 joined_at（存量行回填 now）."""
    op.add_column(
        "project_members",
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """回滚：删除列."""
    op.drop_column("project_members", "joined_at")
