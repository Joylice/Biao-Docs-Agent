"""创建 documents/score_points/tech_requirements/kb_chunks 表.

Revision ID: 0002_documents_kb
Revises: 0001_initial
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0002_documents_kb"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建文档、评分点、技术需求、资料库分块表."""
    # 启用 pgvector 扩展（kb_chunks.embedding 依赖）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # documents
    op.create_table(
        "documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(30), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])

    # score_points
    op.create_table(
        "score_points",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("clause_no", sa.Text(), nullable=False),
        sa.Column("item", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("criteria", sa.Text(), nullable=True),
        sa.Column("is_star", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(10), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_score_points_project_id", "score_points", ["project_id"])

    # tech_requirements
    op.create_table(
        "tech_requirements",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_tech_req_project_id", "tech_requirements", ["project_id"])

    # kb_chunks (with pgvector)
    op.create_table(
        "kb_chunks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_kb_chunks_doc_id", "kb_chunks", ["doc_id"])


def downgrade() -> None:
    """回滚."""
    op.drop_table("kb_chunks")
    op.drop_index("ix_tech_req_project_id", table_name="tech_requirements")
    op.drop_table("tech_requirements")
    op.drop_index("ix_score_points_project_id", table_name="score_points")
    op.drop_table("score_points")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
