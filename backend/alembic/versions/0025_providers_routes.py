"""新增 llm_providers + model_routes 表 — 服务商注册与模型路由.

参照 OpenMAIC provider-neutral routing 设计，将原 llm_settings 表的硬编码
密钥列升级为独立 provider 注册表，并新增按流水线阶段的模型路由表。

- llm_providers: 每行一个 provider，含 prefix/api_key_enc/capabilities/enabled
- model_routes: 每行一个流水线阶段，含 model/fallback/thinking/temperature

旧 llm_settings 表保留为全局 fallback（embedding/mock 等仍走旧表）。

Revision ID: 0025_providers_routes
Revises: 0024_content_dsl
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_providers_routes"
down_revision: str | None = "0024_content_dsl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 llm_providers 和 model_routes 表."""
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("prefix", sa.String(64), nullable=False, unique=True),
        sa.Column("api_key_enc", sa.String(512), nullable=True),
        sa.Column("api_base", sa.String(512), nullable=True),
        sa.Column("default_base", sa.String(512), nullable=True),
        sa.Column("cap_text", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("cap_embedding", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("cap_rerank", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("cap_vision", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("builtin", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("models", sa.String(1024), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "model_routes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("stage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("stage_name", sa.String(128), nullable=False),
        sa.Column("node_name", sa.String(128), nullable=False),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("fallback", sa.String(1024), nullable=True),
        sa.Column("thinking", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("timeout", sa.Integer, nullable=True),
        sa.Column("hint", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 迁移内置 provider 数据（从 llm_settings 表已有密钥迁移）
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), 'DeepSeek', 'deepseek',
                (SELECT deepseek_api_key_enc FROM llm_settings LIMIT 1),
                'https://api.deepseek.com/v1',
                true, false, false, false, true, true,
                'deepseek-chat,deepseek-reasoner,deepseek-coder')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), '智谱 GLM', 'zhipu',
                (SELECT zhipu_api_key_enc FROM llm_settings LIMIT 1),
                'https://open.bigmodel.cn/api/paas/v4',
                true, true, false, true, true, true,
                'glm-4-plus,glm-4-flash,glm-4v,embedding-3')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), '阿里云百炼', 'dashscope',
                (SELECT dashscope_api_key_enc FROM llm_settings LIMIT 1),
                'https://dashscope.aliyuncs.com/compatible-mode/v1',
                true, true, true, true, true, true,
                'qwen-plus,qwen-max,qwen-turbo,text-embedding-v3,gte-rerank')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), '月之暗面 Kimi', 'moonshot',
                (SELECT moonshot_api_key_enc FROM llm_settings LIMIT 1),
                'https://api.moonshot.cn/v1',
                true, false, false, false, true, false,
                'moonshot-v1-8k,moonshot-v1-32k,moonshot-v1-128k')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), 'OpenAI', 'openai',
                (SELECT openai_api_key_enc FROM llm_settings LIMIT 1),
                'https://api.openai.com/v1',
                true, true, false, true, true, false,
                'gpt-4o,gpt-4o-mini,text-embedding-3-small')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, default_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), 'Anthropic', 'anthropic',
                (SELECT anthropic_api_key_enc FROM llm_settings LIMIT 1),
                'https://api.anthropic.com',
                true, false, false, true, true, false,
                'claude-sonnet-4,claude-opus-4')
        ON CONFLICT (prefix) DO NOTHING
        """
    )
    # 自定义端点（从 llm_settings 迁移）
    op.execute(
        """
        INSERT INTO llm_providers (id, name, prefix, api_key_enc, api_base, cap_text, cap_embedding, cap_rerank, cap_vision, builtin, enabled, models)
        VALUES
            (gen_random_uuid(), '自定义端点', 'custom',
                (SELECT llm_api_key_enc FROM llm_settings LIMIT 1),
                (SELECT llm_api_base FROM llm_settings LIMIT 1),
                true, false, false, false, false, true,
                'qwen72b,qwen-14b')
        ON CONFLICT (prefix) DO NOTHING
        """
    )

    # 迁移默认路由数据
    op.execute(
        """
        INSERT INTO model_routes (id, stage_key, stage_name, node_name, model, fallback, thinking, temperature, max_tokens, timeout, hint, enabled)
        VALUES
            (gen_random_uuid(), 'parse', '招标解析', 'parse_node', 'deepseek/deepseek-chat', '["zhipu/glm-4-flash"]', false, 0.1, 4096, 60, '', true),
            (gen_random_uuid(), 'score', '评分对标', 'confirm_score_points_node', 'deepseek/deepseek-chat', '[]', false, 0.1, 4096, 60, '', true),
            (gen_random_uuid(), 'outline', '骨架生成', 'generate_outline_node', 'zhipu/glm-4-plus', '["deepseek/deepseek-chat","dashscope/qwen-max"]', true, 0.3, 8192, 120, '大纲需覆盖招标文件全部评分点', true),
            (gen_random_uuid(), 'write', '章节生成', 'write_node', 'custom/qwen72b', '["zhipu/glm-4-plus","deepseek/deepseek-chat"]', true, 0.5, 16384, 300, '每章节独立生成，需引用知识库内容', true),
            (gen_random_uuid(), 'validate', '一致性校验', 'validate_node', 'deepseek/deepseek-chat', '["zhipu/glm-4-flash"]', false, 0.1, 4096, 60, '', true),
            (gen_random_uuid(), 'review', '审阅重写', 'review_node', 'deepseek/deepseek-reasoner', '["zhipu/glm-4-plus"]', true, 0.3, 8192, 120, '依据评分标准逐条审查', true),
            (gen_random_uuid(), 'export', '导出', 'export_node', null, '[]', false, null, null, null, '无 LLM 调用，纯文档渲染', true)
        ON CONFLICT (stage_key) DO NOTHING
        """
    )


def downgrade() -> None:
    """回滚：删除 model_routes 和 llm_providers 表."""
    op.drop_table("model_routes")
    op.drop_table("llm_providers")
