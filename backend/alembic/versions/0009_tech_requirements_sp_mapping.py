"""tech_requirements 新增评分点映射字段（sp_id/source）.

评分点确认 → 技术需求梳理功能：sp_derived 需求回溯归属的评分点；
source 区分衍生需求（sp_derived）与招标原文独立提取需求（tender）。
存量数据两列均为 NULL（视为招标原文提取、不归属具体评分点）。

Revision ID: 0009_tech_req_sp_mapping
Revises: 0008_documents_category_tags
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# 注意：alembic_version.version_num 为 varchar(32)，revision id 不得超长
revision: str = "0009_tech_req_sp_mapping"
down_revision: str | None = "0008_documents_category_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 sp_id（归属评分点，可空）与 source（需求来源，可空）."""
    op.add_column(
        "tech_requirements",
        sa.Column("sp_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tech_requirements_sp_id",
        "tech_requirements",
        "score_points",
        ["sp_id"],
        ["id"],
        # 评分点被重解析清除时，衍生需求保留但解除归属
        ondelete="SET NULL",
    )
    op.add_column(
        "tech_requirements",
        sa.Column("source", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除外键与两列."""
    op.drop_constraint("fk_tech_requirements_sp_id", "tech_requirements", type_="foreignkey")
    op.drop_column("tech_requirements", "source")
    op.drop_column("tech_requirements", "sp_id")
