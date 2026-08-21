"""chapter_assignments 新增章节内容字段（content Markdown + content_html 富文本 HTML）.

章节内容读写端点 GET/PUT /projects/{pid}/chapters/{chapter_no}/content 的存储载体：
content 为 Markdown 源（存量行以空串兜底），content_html 为富文本编辑器 HTML 主存储（可空）。

Revision ID: 0018_chapter_content
Revises: 0017_disqualification_clauses
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# 注意：alembic_version.version_num 为 varchar(32)，revision id 不得超长
revision: str = "0018_chapter_content"
down_revision: str | None = "0017_disqualification_clauses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增章节正文 Markdown 与富文本 HTML 两列（仅加列）."""
    op.add_column(
        "chapter_assignments",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "chapter_assignments",
        sa.Column("content_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除两列."""
    op.drop_column("chapter_assignments", "content_html")
    op.drop_column("chapter_assignments", "content")
