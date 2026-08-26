"""一次性修复脚本：用真实 Embedding 重算存量 kb_chunks 向量.

背景：mock 模式下索引的分块向量为 sha256 伪向量，切回真实模式后
查询向量（bge-m3）与伪向量相似度恒为负，导致检索零命中。
本脚本读取所有分块原文，批量调用真实 Embedding 服务重建向量。

用法（api 容器内 /app 目录）：python -m scripts.reembed_chunks
"""

import asyncio

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.models.kb_chunk import KbChunk
from app.services.llm.rag_service import get_embeddings_batch

BATCH = 10  # DashScope embedding 批量上限 10


async def main() -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(select(KbChunk.id, KbChunk.content))).all()
        print(f"total chunks: {len(rows)}")
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            vectors = await get_embeddings_batch([r.content for r in batch])
            for row, vec in zip(batch, vectors, strict=True):
                await db.execute(
                    update(KbChunk).where(KbChunk.id == row.id).values(embedding=vec.tolist())
                )
            print(f"re-embedded {min(i + BATCH, len(rows))}/{len(rows)}")
        await db.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
