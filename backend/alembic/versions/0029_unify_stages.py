"""统一投标编制节点 — 删除 rewrite 行 + 改名 stage_name.

将 9 个 stage_key 的展示名统一到 5 个投标编制节点：
- 招标解析（parse + score）
- 方案大纲生成（outline）
- 方案生成（write + validate + consistency）
- 方案评审（review）—— rewrite 行删除，用量日志归并
- 方案导出（export）

DB 行只删 rewrite（其余保留，stage_key 不变），仅更新 stage_name 中文名。
service 层 stage_key 参数不变，前端展示层做归并映射。

Revision ID: 0029_unify_stages
Revises: 0028_retrieval_configs
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_unify_stages"
down_revision: str | None = "0028_retrieval_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """删除 rewrite 路由行 + 归并用量日志 + 改名 stage_name."""

    # 1. 删除 rewrite 路由行（前端不再暴露此阶段）
    op.execute("DELETE FROM model_routes WHERE stage_key = 'rewrite'")

    # 2. llm_usage_log 历史 rewrite 用量归入 review
    op.execute("UPDATE llm_usage_log SET stage_key = 'review' WHERE stage_key = 'rewrite'")

    # 3. stage_tool_bindings 里 rewrite 绑定归入 review
    op.execute("UPDATE stage_tool_bindings SET stage_key = 'review' WHERE stage_key = 'rewrite'")

    # 4. stage_name 中文名统一到投标编制节点命名
    op.execute("UPDATE model_routes SET stage_name = '招标解析' WHERE stage_key = 'parse'")
    op.execute("UPDATE model_routes SET stage_name = '评分对标' WHERE stage_key = 'score'")
    op.execute("UPDATE model_routes SET stage_name = '方案大纲生成' WHERE stage_key = 'outline'")
    op.execute("UPDATE model_routes SET stage_name = '方案生成' WHERE stage_key = 'write'")
    op.execute("UPDATE model_routes SET stage_name = '方案校验' WHERE stage_key = 'validate'")
    op.execute("UPDATE model_routes SET stage_name = '一致性校验' WHERE stage_key = 'consistency'")
    op.execute("UPDATE model_routes SET stage_name = '方案评审' WHERE stage_key = 'review'")
    op.execute("UPDATE model_routes SET stage_name = '方案导出' WHERE stage_key = 'export'")


def downgrade() -> None:
    """回滚：恢复 rewrite 行 + 旧 stage_name."""
    op.execute(
        """
        INSERT INTO model_routes (id, stage_key, stage_name, node_name, model, fallback, thinking, temperature, max_tokens, timeout, hint, enabled)
        VALUES
            (gen_random_uuid(), 'rewrite', '审阅重写', 'rewrite_node', 'deepseek/deepseek-reasoner', '["zhipu/glm-4-plus"]', true, 0.3, 8192, 120, '依据评分标准逐条审查', true)
        ON CONFLICT (stage_key) DO NOTHING
        """
    )
    op.execute(
        "UPDATE llm_usage_log SET stage_key = 'rewrite' "
        "WHERE stage_key = 'review' AND stage_key = 'rewrite'"
    )
    op.execute("UPDATE stage_tool_bindings SET stage_key = 'rewrite' WHERE stage_key = 'review'")
    op.execute("UPDATE model_routes SET stage_name = '招标解析' WHERE stage_key = 'parse'")
    op.execute("UPDATE model_routes SET stage_name = '评分对标' WHERE stage_key = 'score'")
    op.execute("UPDATE model_routes SET stage_name = '骨架生成' WHERE stage_key = 'outline'")
    op.execute("UPDATE model_routes SET stage_name = '章节生成' WHERE stage_key = 'write'")
    op.execute("UPDATE model_routes SET stage_name = '一致性校验' WHERE stage_key = 'validate'")
    op.execute("UPDATE model_routes SET stage_name = '一致性校验' WHERE stage_key = 'consistency'")
    op.execute("UPDATE model_routes SET stage_name = '审阅重写' WHERE stage_key = 'review'")
    op.execute("UPDATE model_routes SET stage_name = '导出' WHERE stage_key = 'export'")
