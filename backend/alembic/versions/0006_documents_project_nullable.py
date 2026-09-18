"""documents.project_id 改为可空（支持全局资料库：kb_material 独立于项目管理）.

Revision ID: 0006_documents_project_nullable
Revises: 0005_llm_settings
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_documents_project_nullable"
down_revision: str | None = "0005_llm_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """documents.project_id 允许为空（project_id IS NULL = 全局共享资料库）."""
    op.alter_column("documents", "project_id", nullable=True)


def downgrade() -> None:
    """回滚：删除全局资料后再收紧约束."""
    op.execute("DELETE FROM documents WHERE project_id IS NULL")
    op.alter_column("documents", "project_id", nullable=False)
