"""llm_usage_log 加 agent_id/skill_name 两列 — S5 归因与可观测

Revision ID: 0032_llm_usage_log_skill
Revises: 0031_user_skills
Create Date: 2026-09-18

SKILL.md 契约体系 S5：让「改完某条 skill 的准则后看指标变了没有」有据可查。
- agent_id VARCHAR(64) NULL：agent 粒度归因（向后兼容，既有行为不变）；
- skill_name VARCHAR(64) NULL：skill 粒度归因（本次改造独有的观测维度）；
- 索引 (skill_name, created_at) 服务 GET /usage/skill-profiles 的时间窗聚合。

两列均可空 + 无默认值约束：迁移前历史行自然为 NULL，聚合层归入 "unknown"，
不回填不重算 —— 纯增量迁移，不锁表（PG 11+ ADD COLUMN 无默认值仅元数据变更）。
"""

# revision identifiers, used by Alembic.
revision: str = "0032_llm_usage_log_skill"
down_revision: str = "0031_user_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agent_id/skill_name columns + skill attribution index."""
    import sqlalchemy as sa

    from alembic import op

    op.add_column("llm_usage_log", sa.Column("agent_id", sa.String(64), nullable=True))
    op.add_column("llm_usage_log", sa.Column("skill_name", sa.String(64), nullable=True))
    op.create_index(
        "ix_llm_usage_log_skill_created",
        "llm_usage_log",
        ["skill_name", "created_at"],
    )


def downgrade() -> None:
    """Drop skill attribution index and columns (attribution history is lost)."""
    from alembic import op

    op.drop_index("ix_llm_usage_log_skill_created", table_name="llm_usage_log")
    op.drop_column("llm_usage_log", "skill_name")
    op.drop_column("llm_usage_log", "agent_id")
