"""外部工具表 + 阶段绑定表 — Phase 2 Tavily 式外部工具系统.

- external_tools: 外部搜索工具注册表（Tavily/Brave/SearXNG 预设 + 自定义 HTTP），
  密钥 Fernet 加密入库，按 preset 注入请求（bearer_body/header_token/none）；
- stage_tool_bindings: 工具 → 流水线阶段绑定（复合主键，ON DELETE CASCADE），
  仅 parse/outline/write/validate 在白名单内，供 registry.get_definitions 动态组装
  OpenAI function schema。

无数据回填（新表，首次部署时为空）。

Revision ID: 0027_external_tools
Revises: 0026_stage_routing_usage
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_external_tools"
down_revision: str | None = "0026_stage_routing_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 external_tools 和 stage_tool_bindings 表."""
    op.create_table(
        "external_tools",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("preset", sa.String(32), nullable=False, server_default="custom"),
        sa.Column("tool_type", sa.String(32), nullable=False, server_default="http_search"),
        sa.Column("api_key_enc", sa.String(512), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("timeout_ms", sa.Integer, nullable=False, server_default=sa.text("10000")),
        sa.Column("max_query_chars", sa.Integer, nullable=False, server_default=sa.text("400")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "stage_tool_bindings",
        sa.Column(
            "tool_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_tools.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stage_key", sa.String(64), primary_key=True),
    )


def downgrade() -> None:
    """回滚：删除 stage_tool_bindings 和 external_tools 表."""
    op.drop_table("stage_tool_bindings")
    op.drop_table("external_tools")
