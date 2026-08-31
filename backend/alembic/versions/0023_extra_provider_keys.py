"""扩展 llm_settings：追加主流模型提供商 API Key.

追加 OpenAI / Anthropic / 智谱 AI / 月之暗面 四家主流提供商的密钥字段，
支持用户在页面配置后按模型前缀自动匹配使用。

- openai_api_key_enc：OpenAI 官方 API 密钥
- anthropic_api_key_enc：Anthropic Claude API 密钥
- zhipu_api_key_enc：智谱 AI GLM 系列密钥
- moonshot_api_key_enc：月之暗面 Kimi 密钥

Revision ID: 0023_extra_provider_keys
Revises: 0022_llm_api_key
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_extra_provider_keys"
down_revision: str | None = "0022_llm_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """追加4个提供商密钥列."""
    op.add_column("llm_settings", sa.Column("openai_api_key_enc", sa.String(512), nullable=True))
    op.add_column("llm_settings", sa.Column("anthropic_api_key_enc", sa.String(512), nullable=True))
    op.add_column("llm_settings", sa.Column("zhipu_api_key_enc", sa.String(512), nullable=True))
    op.add_column("llm_settings", sa.Column("moonshot_api_key_enc", sa.String(512), nullable=True))


def downgrade() -> None:
    """回滚."""
    op.drop_column("llm_settings", "moonshot_api_key_enc")
    op.drop_column("llm_settings", "zhipu_api_key_enc")
    op.drop_column("llm_settings", "anthropic_api_key_enc")
    op.drop_column("llm_settings", "openai_api_key_enc")
