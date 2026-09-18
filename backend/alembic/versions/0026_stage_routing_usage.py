"""阶段路由回填 + llm_usage_log 用量日志表 — Phase 1 模型路由运行时.

- llm_usage_log: LLM 调用埋点（成功/失败各一行，异步 fire-and-forget 写入），
  支持 GET /usage/summary 按 stage/model 聚合（次数/成功率/token/平均延迟）。
- model_routes 数据回填：读 llm_settings 单行 llm_model，为 8 个 stage_key 各插
  一行（model=旧全局模型，其余参数 NULL，enabled=true），幂等（已存在跳过，
  hint='0026_backfill' 标记回填来源，downgrade 按标记精确清理）。

Revision ID: 0026_stage_routing_usage
Revises: 0025_providers_routes
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_stage_routing_usage"
down_revision: str | None = "0025_providers_routes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 llm_usage_log 表 + 回填 model_routes 阶段路由."""
    op.create_table(
        "llm_usage_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_key", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=True),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("ok", sa.Boolean, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("total_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("fallback_used", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_llm_usage_log_project_created",
        "llm_usage_log",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_llm_usage_log_stage_created",
        "llm_usage_log",
        ["stage_key", "created_at"],
    )

    # 数据回填：8 个 stage_key 各插一行 model_routes（model=旧 llm_settings.llm_model，
    # 其余参数 NULL，enabled=true）；幂等——已存在（含 0025 内置路由）跳过。
    # stage_name/node_name 为 NOT NULL 列，按图节点语义补齐；hint 标记回填来源。
    op.execute(
        """
        INSERT INTO model_routes (id, stage_key, stage_name, node_name, model, enabled, hint)
        SELECT gen_random_uuid(), s.stage_key, s.stage_name, s.node_name,
               (SELECT llm_model FROM llm_settings LIMIT 1),
               true, '0026_backfill'
        FROM (VALUES
            ('parse',       '招标解析',   'parse_node'),
            ('score',       '评分对标',   'confirm_score_points_node'),
            ('outline',     '骨架生成',   'generate_outline_node'),
            ('write',       '章节生成',   'write_node'),
            ('validate',    '一致性校验', 'validate_node'),
            ('consistency', '全文一致性', 'consistency_check_node'),
            ('review',      '审阅重写',   'review_node'),
            ('rewrite',     '定向重写',   'rewrite_node')
        ) AS s(stage_key, stage_name, node_name)
        WHERE (SELECT llm_model FROM llm_settings LIMIT 1) IS NOT NULL
        ON CONFLICT (stage_key) DO NOTHING
        """
    )


def downgrade() -> None:
    """回滚：删除回填路由行与 llm_usage_log 表."""
    op.execute("DELETE FROM model_routes WHERE hint = '0026_backfill'")
    op.drop_index("ix_llm_usage_log_stage_created", table_name="llm_usage_log")
    op.drop_index("ix_llm_usage_log_project_created", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
