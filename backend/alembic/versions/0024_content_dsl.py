"""新增 content_dsl JSON 列：proposal_sections + chapter_assignments.

Content DSL（结构化内容表示）替代 Markdown 字符串作为内容真源。
DSL JSON 树既是存储格式，也是渲染格式，也是编辑格式（参照 OpenMAIC @openmaic/dsl）。

- proposal_sections.content_dsl：章节正文 DSL JSON（可空，惰性迁移填充）
- chapter_assignments.content_dsl：分工编制内容 DSL JSON（可空）

旧数据兼容：content_dsl 为 NULL 时回退 content_md Markdown 解析。

Revision ID: 0024_content_dsl
Revises: 0023_extra_provider_keys
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_content_dsl"
down_revision: str | None = "0023_extra_provider_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 content_dsl JSON 列（可空，惰性迁移）."""
    op.add_column(
        "proposal_sections",
        sa.Column("content_dsl", sa.JSON(), nullable=True),
    )
    op.add_column(
        "chapter_assignments",
        sa.Column("content_dsl", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除 content_dsl 列."""
    op.drop_column("chapter_assignments", "content_dsl")
    op.drop_column("proposal_sections", "content_dsl")
