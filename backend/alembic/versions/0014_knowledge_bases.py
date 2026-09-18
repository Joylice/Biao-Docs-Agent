"""知识库容器表 + documents.kb_id（多知识库：个人/项目/公司三级）.

Revision ID: 0014_knowledge_bases
Revises: 0013_chapter_assignments
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_knowledge_bases"
down_revision: str | None = "0013_chapter_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPANY_PUBLIC_BASE_NAME = "公司公共库"


def upgrade() -> None:
    """新建 knowledge_bases 表，documents 增 kb_id，并归档存量全局素材入公司公共库."""
    op.create_table(
        "knowledge_bases",
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
            nullable=True,  # NULL = 个人库 / 公司库（非项目维度）
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,  # NULL = 公司种子库（管理员集体维护）
        ),
        # personal|project|company
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 种子「公司公共库」+ 存量全局素材归档（幂等；名称为代码常量无注入风险）
    op.execute(
        f"""
        INSERT INTO knowledge_bases (id, project_id, owner_id, scope, name, description)
        SELECT gen_random_uuid(), NULL, NULL, 'company', '{COMPANY_PUBLIC_BASE_NAME}',
               '存量全局素材的默认公司级知识库'
        WHERE NOT EXISTS (
            SELECT 1 FROM knowledge_bases
            WHERE scope = 'company' AND name = '{COMPANY_PUBLIC_BASE_NAME}'
        )
        """
    )
    op.execute(
        f"""
        UPDATE documents
        SET kb_id = (
            SELECT id FROM knowledge_bases
            WHERE scope = 'company' AND name = '{COMPANY_PUBLIC_BASE_NAME}' LIMIT 1
        )
        WHERE project_id IS NULL AND doc_type = 'kb_material' AND kb_id IS NULL
        """
    )


def downgrade() -> None:
    """回滚：删除 kb_id 列与 knowledge_bases 表."""
    op.drop_column("documents", "kb_id")
    op.drop_table("knowledge_bases")
