"""chapter_annotations 新增 status 与 selection 字段.

- status: 批注状态（open/resolved），默认 open
- selection: 富文本选区信息（JSON: {from, to, text}），用于批注与正文关联定位

Revision ID: 0020_annotation_status_selection
Revises: 0018_chapter_content
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_annotation_status_selection"
# 迁移链：0018 → 0006_embedding_config → 0019_custom_llm → 0020（本迁移）
# 注意：0019 的 down_revision 也是 0018（此前 0006_embedding_config 已挂在 0018 之后），
# 故本迁移必须挂在 0019 之后保持线性，否则产生双 head 分支。
down_revision: str | None = "0019_custom_llm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增批注状态与选区字段."""
    op.add_column(
        "chapter_annotations",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
    )
    op.add_column(
        "chapter_annotations",
        sa.Column("selection", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除两列."""
    op.drop_column("chapter_annotations", "selection")
    op.drop_column("chapter_annotations", "status")
