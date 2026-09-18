"""kb_chunks.embedding 增加 HNSW 索引（余弦距离 ANN 检索）.

此前 embedding 列无 ANN 索引，检索为全表顺序扫描，资料库增长后
性能线性退化（P1-2.2）。检索 SQL 使用 cosine_distance（<=> 操作符），
故索引 opclass 必须为 vector_cosine_ops 以保证命中。

Revision ID: 0021_kb_chunk_hnsw
Revises: 0020_annotation_status_selection
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_kb_chunk_hnsw"
down_revision: str | None = "0020_annotation_status_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# m=16 / ef_construction=64：pgvector 默认构建参数，中小规模语料的
# 召回/建索引速度平衡点；检索期 ef_search 由会话级 SET 控制（默认 40）。
_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding_hnsw "
    "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
)


def upgrade() -> None:
    """创建 HNSW 余弦索引."""
    op.execute(_INDEX_DDL)


def downgrade() -> None:
    """回滚：删除索引."""
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_hnsw")
