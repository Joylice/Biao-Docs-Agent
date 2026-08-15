"""RAG 服务 — 分块、向量化、检索."""

import hashlib
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BizError
from app.models.kb_chunk import KbChunk


@dataclass
class ChunkResult:
    """检索结果."""

    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    content: str
    page_no: int | None
    score: float


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """将文本按滑动窗口分块."""
    if not text or not text.strip():
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap

    return chunks


async def embed_and_store(
    db: AsyncSession,
    doc_id: uuid.UUID,
    chunks: list[str],
    embeddings: np.ndarray,
    page_numbers: list[int | None] | None = None,
) -> int:
    """将分块 + 向量写入 kb_chunks 表."""
    if len(chunks) != len(embeddings):
        raise BizError(code=5005, message="分块数与向量数不匹配")

    count = 0
    for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
        page_no = page_numbers[i] if page_numbers else None
        kb_chunk = KbChunk(
            doc_id=doc_id,
            chunk_index=i,
            content=chunk_text,
            page_no=page_no,
            embedding=embedding.tolist(),
        )
        db.add(kb_chunk)
        count += 1

    await db.flush()
    return count


async def retrieve_similar(
    db: AsyncSession,
    project_id: uuid.UUID,
    query_embedding: np.ndarray,
    top_k: int = 20,
    threshold: float = 0.3,
) -> list[ChunkResult]:
    """向量相似度检索（cosine distance）."""
    from app.models.document import Document

    # 获取项目下的 doc_ids
    doc_ids_result = await db.execute(select(Document.id).where(Document.project_id == project_id))
    doc_ids = [row[0] for row in doc_ids_result.all()]
    if not doc_ids:
        return []

    # 使用 pgvector 的余弦距离检索
    # cosine_distance = 1 - cosine_similarity
    query = (
        select(
            KbChunk.id,
            KbChunk.doc_id,
            KbChunk.content,
            KbChunk.page_no,
            KbChunk.embedding.cosine_distance(query_embedding.tolist()).label("distance"),
        )
        .where(KbChunk.doc_id.in_(doc_ids))
        .where(KbChunk.embedding.isnot(None))
        .order_by(KbChunk.embedding.cosine_distance(query_embedding.tolist()))
        .limit(top_k)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        ChunkResult(
            chunk_id=row.id,
            doc_id=row.doc_id,
            content=row.content,
            page_no=row.page_no,
            score=1.0 - row.distance,  # 转换为相似度
        )
        for row in rows
        if (1.0 - row.distance) >= threshold
    ]


def _is_mock_mode(mock: bool | None) -> bool:
    """判断是否启用 mock：函数参数优先，其次运行时读取 settings.llm_mock."""
    return settings.llm_mock if mock is None else mock


def _mock_embedding(text: str) -> np.ndarray:
    """基于文本 hash 生成确定性伪向量（相同文本 → 相同向量）."""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(settings.embedding_dimension).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


async def get_embedding(text: str, *, mock: bool | None = None) -> np.ndarray:
    """调用 bge-m3 Embedding 服务获取向量."""
    if _is_mock_mode(mock):
        return _mock_embedding(text)
    try:
        from litellm import aembedding

        response = await aembedding(
            model=settings.embedding_model,
            input=[text],
            api_base=settings.embedding_api_base,
        )
        return np.array(response.data[0]["embedding"], dtype=np.float32)
    except Exception as e:
        raise BizError(code=5006, message=f"Embedding 服务调用失败: {e}") from None


async def get_embeddings_batch(texts: list[str], *, mock: bool | None = None) -> np.ndarray:
    """批量获取 Embedding 向量."""
    if _is_mock_mode(mock):
        return np.stack([_mock_embedding(t) for t in texts])
    try:
        from litellm import aembedding

        response = await aembedding(
            model=settings.embedding_model,
            input=texts,
            api_base=settings.embedding_api_base,
        )
        embeddings = [item["embedding"] for item in response.data]
        return np.array(embeddings, dtype=np.float32)
    except Exception as e:
        raise BizError(code=5006, message=f"Embedding 服务调用失败: {e}") from None
