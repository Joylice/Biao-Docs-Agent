"""users 表新增 role 列（三期 S1：角色细分 member/kb_admin/admin）.

Revision ID: 0007_users_role
Revises: 0006_documents_project_nullable
Create Date: 2026-08-16
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_users_role"
down_revision: str | None = "0006_documents_project_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 users.role（默认 member）并按 BID_ADMIN_USER_IDS 回填 admin（幂等）."""
    op.add_column(
        "users",
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
    )
    # 回填：env 白名单命中的邮箱置 admin（迁移遗漏时 deps 仍有白名单兜底，此处尽力回填）
    admins = [
        s.strip().lower() for s in os.environ.get("BID_ADMIN_USER_IDS", "").split(",") if s.strip()
    ]
    if admins:
        op.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE lower(email) IN :emails").bindparams(
                sa.bindparam("emails", expanding=True, value=admins)
            )
        )


def downgrade() -> None:
    """回滚：删除 role 列（恢复为邮箱白名单机制）."""
    op.drop_column("users", "role")
