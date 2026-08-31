"""扩展 llm_settings：自定义 LLM 端点专用密钥.

补齐"需要鉴权的私有化端点"场景：0019 引入 llm_api_base 后，自定义端点调用时
api_key 被硬编码为 "EMPTY" 占位，导致带鉴权的私有化部署（如带 token 的 vLLM
网关、企业内部大模型中台）无法在页面配置凭据。

- llm_api_key_enc：llm_api_base 指向端点的专用密钥（Fernet 密文），
  仅在该端点调用时使用，不参与 deepseek/dashscope 云端密钥匹配，
  避免用户凭据被转发至第三方端点。

Revision ID: 0022_llm_api_key
Revises: 0021_kb_chunk_hnsw
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_llm_api_key"
down_revision: str | None = "0021_kb_chunk_hnsw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加 llm_api_key_enc 列."""
    op.add_column("llm_settings", sa.Column("llm_api_key_enc", sa.String(512), nullable=True))


def downgrade() -> None:
    """回滚."""
    op.drop_column("llm_settings", "llm_api_key_enc")
