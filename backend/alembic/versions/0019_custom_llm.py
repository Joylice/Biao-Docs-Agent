"""扩展 llm_settings：自定义 LLM 主模型与服务地址可页面化配置.

支持"无 key 的 OpenAI 兼容端点"场景（如 vLLM 部署的 qwen72b）：
- llm_model：运行时主模型名（可带 litellm provider 前缀；无前缀自动补 openai_like/）
- llm_api_base：OpenAI 兼容服务地址（http/https，SSRF 校验），留空回退模型前缀默认端点

Revision ID: 0019_custom_llm
Revises: 0006_embedding_config
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_custom_llm"
down_revision: str | None = "0006_embedding_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加 llm_model、llm_api_base 列."""
    op.add_column("llm_settings", sa.Column("llm_model", sa.String(256), nullable=True))
    op.add_column("llm_settings", sa.Column("llm_api_base", sa.String(512), nullable=True))


def downgrade() -> None:
    """回滚."""
    op.drop_column("llm_settings", "llm_api_base")
    op.drop_column("llm_settings", "llm_model")
