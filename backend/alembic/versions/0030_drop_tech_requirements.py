"""drop tech_requirements table

Revision ID: 0030_drop_tech_requirements
Revises: 0029_unify_stages
Create Date: 2026-09-15

P3：技术需求全链路移除，删除 tech_requirements 表。
G3 已签署（王蒙授权 2026-09-15）。
"""

# revision identifiers, used by Alembic.
revision: str = "0030_drop_tech_requirements"
down_revision: str = "0029_unify_stages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop tech_requirements table."""
    from alembic import op

    op.drop_table("tech_requirements")


def downgrade() -> None:
    """Recreate tech_requirements table (non-recovery: data is lost).

    警告：downgrade 仅重建表结构，不恢复历史数据。
    """
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    from alembic import op

    op.create_table(
        "tech_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("sp_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["sp_id"], ["score_points.id"], ondelete="SET NULL"),
    )
