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
from app.services.infra import settings_service


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
    doc_ids: list[uuid.UUID] | None = None,
) -> list[ChunkResult]:
    """向量相似度检索（cosine distance）.

    doc_ids: 资料库挂载配置 — 非 None 时仅检索指定文档的分块（空列表=不挂载）；
    None 时检索项目全部文档（原行为）。
    """
    from app.models.document import Document

    # 获取项目下的 doc_ids（挂载配置显式传入时跳过全量查询）
    if doc_ids is None:
        doc_ids_result = await db.execute(
            select(Document.id).where(Document.project_id == project_id)
        )
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


async def search_materials(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    doc_ids: list[uuid.UUID] | None = None,
) -> list[dict]:
    """资料库检索（API 层入口）：查询文本 → embedding → 召回+精排 → 补文档标题.

    doc_ids: 显式指定检索范围（全局资料库等跨项目场景传 doc_ids 过滤）；
    None 时按 project_id 检索项目文档。
    min_score 默认 0：按相似度倒序返回 top_k 条。LLM mock 模式下 embedding
    为确定性伪向量，相似度在 [-1,1] 随机分布（可能为负），阈值自动放宽到
    -1 以免概率性零命中；生产（真实 embedding）按 min_score 过滤。
    只读操作，不 commit（事务约定见 core.database.get_db）。
    """
    from app.models.document import Document

    mock_enabled = await settings_service.is_mock_enabled()
    query_embedding = await get_embedding(query)
    results = await retrieve_with_rerank(
        db=db,
        project_id=project_id,
        query=query,
        query_embedding=query_embedding,
        top_k=top_k,
        threshold=-1.0 if mock_enabled else min_score,
        doc_ids=doc_ids,
    )
    if not results:
        return []

    # 补齐命中分块所属文档的标题
    doc_ids = list({r.doc_id for r in results})
    title_result = await db.execute(
        select(Document.id, Document.title).where(Document.id.in_(doc_ids))
    )
    titles = {row[0]: row[1] for row in title_result.all()}

    return [
        {
            "chunk_id": str(r.chunk_id),
            "doc_id": str(r.doc_id),
            "title": titles.get(r.doc_id, ""),
            "content": r.content,
            "page_no": r.page_no,
            "score": round(float(r.score), 4),
        }
        for r in results
    ]


# rerank 精排召回候选池（向量召回放宽到该数量，精排后截断到请求 top_k）
RERANK_RECALL_K = 30


async def retrieve_with_rerank(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    query_embedding: np.ndarray,
    top_k: int = 8,
    threshold: float = 0.3,
    doc_ids: list[uuid.UUID] | None = None,
) -> list[ChunkResult]:
    """向量召回（候选池放宽）→ rerank 精排 → 取前 top_k.

    rerank 直通/降级语义由 rerank_service 保证（mock/未启用/失败 → 原向量序），
    本函数不感知精排是否真实发生。
    """
    # 延迟 import 避免循环依赖（rerank_service 引用本模块 ChunkResult）
    from app.services.llm import rerank_service

    candidates = await retrieve_similar(
        db=db,
        project_id=project_id,
        query_embedding=query_embedding,
        top_k=max(top_k, RERANK_RECALL_K),
        threshold=threshold,
        doc_ids=doc_ids,
    )
    return await rerank_service.rerank(query, candidates, top_n=top_k)


def _mock_embedding(text: str) -> np.ndarray:
    """基于文本 hash 生成确定性伪向量（相同文本 → 相同向量）."""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(settings.embedding_dimension).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


async def _embedding_model() -> str:
    """库内配置优先：页面配置的 embedding_model 覆盖 env，无则回退 env.

    容错（易用性）：模型名未携带 LiteLLM provider 前缀（不含 "/"）时，
    自动补 ``openai_like/`` —— 兼容用户直接填 ``jiaorong-bge-m3``/``bge-m3``
    等 OpenAI 兼容接口模型名，避免 "LLM Provider NOT provided" 报错。
    """
    model = (await _embedding_cfg_model()) or settings.embedding_model
    if "/" not in model:
        return f"openai_like/{model}"
    return model


async def _embedding_cfg_model() -> str | None:
    """读取库内页面配置的 embedding_model（无则 None）."""
    cfg = await settings_service.get_runtime_config()
    return cfg.embedding_model if cfg else None


async def _embedding_api_base() -> str:
    """库内配置优先：页面配置的 embedding_api_base 覆盖 env，无则回退 env."""
    cfg = await settings_service.get_runtime_config()
    return (cfg.embedding_api_base if cfg else None) or settings.embedding_api_base


async def _embedding_api_key_kwargs() -> dict[str, str]:
    """库内密钥优先：embedding 专用密钥 > 模型前缀匹配密钥 > 回退 env（不传参）."""
    cfg = await settings_service.get_runtime_config()
    if cfg is None:
        return {}
    # 优先使用 embedding 专用密钥；其次按模型前缀匹配 deepseek/dashscope 密钥
    model = await _embedding_model()
    api_key = cfg.embedding_api_key or cfg.api_key_for(model)
    return {"api_key": api_key} if api_key else {}


async def get_embedding(text: str, *, mock: bool | None = None) -> np.ndarray:
    """调用 Embedding 服务获取向量."""
    if await settings_service.is_mock_enabled(mock):
        return _mock_embedding(text)
    try:
        from litellm import aembedding

        response = await aembedding(
            model=await _embedding_model(),
            input=[text],
            api_base=await _embedding_api_base(),
            **await _embedding_api_key_kwargs(),
        )
        return np.array(response.data[0]["embedding"], dtype=np.float32)
    except Exception as e:
        raise BizError(code=5006, message=f"Embedding 服务调用失败: {e}") from None


async def get_embeddings_batch(texts: list[str], *, mock: bool | None = None) -> np.ndarray:
    """批量获取 Embedding 向量."""
    if await settings_service.is_mock_enabled(mock):
        return np.stack([_mock_embedding(t) for t in texts])
    try:
        from litellm import aembedding

        response = await aembedding(
            model=await _embedding_model(),
            input=texts,
            api_base=await _embedding_api_base(),
            **await _embedding_api_key_kwargs(),
        )
        embeddings = [item["embedding"] for item in response.data]
        return np.array(embeddings, dtype=np.float32)
    except Exception as e:
        raise BizError(code=5006, message=f"Embedding 服务调用失败: {e}") from None
