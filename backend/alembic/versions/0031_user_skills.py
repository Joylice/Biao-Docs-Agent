"""user_skills 表 — SKILL.md 契约体系的用户侧存储

Revision ID: 0031_user_skills
Revises: 0030_drop_tech_requirements
Create Date: 2026-09-18

引入 SKILL.md 契约体系：内置层走文件系统（backend/skills/*/SKILL.md），
用户层走本表。两层由 services/skills/registry.list_skills 合并，同名用户层覆盖内置层。

列说明见 app/models/user_skill.py 模块 docstring。
本迁移纯增量（新建表），不动任何既有表。
"""

# revision identifiers, used by Alembic.
revision: str = "0031_user_skills"
down_revision: str = "0030_drop_tech_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create user_skills table."""
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    from alembic import op

    op.create_table(
        "user_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("skill_version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("stage_key", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(16), nullable=False, server_default="user"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("name", name="uq_user_skills_name"),
    )
    op.create_index("ix_user_skills_name", "user_skills", ["name"])
    op.create_index("ix_user_skills_owner_id", "user_skills", ["owner_id"])
    op.create_index("ix_user_skills_stage_key", "user_skills", ["stage_key"])


def downgrade() -> None:
    """Drop user_skills table (non-recovery: user-authored skills are lost)."""
    from alembic import op

    op.drop_index("ix_user_skills_stage_key", table_name="user_skills")
    op.drop_index("ix_user_skills_owner_id", table_name="user_skills")
    op.drop_index("ix_user_skills_name", table_name="user_skills")
    op.drop_table("user_skills")
