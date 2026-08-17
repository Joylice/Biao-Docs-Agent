"""proposal_skeletons 新增大纲二次编辑草稿字段（draft/draft_updated_at）.

方案生成页「大纲编辑」卡片防丢失：编辑副本随自动防抖/手动保存落库；
确认大纲（confirm-outline）成功后由节点清空，防陈旧草稿下次误恢复。

Revision ID: 0010_skeleton_outline_draft
Revises: 0009_tech_req_sp_mapping
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# 注意：alembic_version.version_num 为 varchar(32)，revision id 不得超长
revision: str = "0010_skeleton_outline_draft"
down_revision: str | None = "0009_tech_req_sp_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增草稿 JSON（{"outline": [...], "mounted_doc_ids": [...]}）与更新时间."""
    op.add_column(
        "proposal_skeletons",
        sa.Column("draft", sa.JSON(), nullable=True),
    )
    op.add_column(
        "proposal_skeletons",
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除两列."""
    op.drop_column("proposal_skeletons", "draft_updated_at")
    op.drop_column("proposal_skeletons", "draft")
