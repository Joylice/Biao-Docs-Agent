"""异步任务定义 — Arq worker 执行."""

import logging
import uuid
from typing import Any, TypeGuard

logger = logging.getLogger(__name__)


async def task_parse_tender(
    ctx: dict[str, Any], project_id: str, doc_id: str, score_points_only: bool = False
) -> dict[str, Any]:
    """异步任务：解析招标文件.

    P1 改造：挂钩多智能体编排（parse_tender_multi_agent），
    旧 parse_tender_with_llm 作为降级回退路径保留。

    score_points_only 参数保留但不再影响 LLM 调用分支（签名收敛）：
    多 Agent 模式下所有提取 Agent 均参与，不再有"只提取评分点"模式。
    P3 技术需求移除后此参数将被彻底删除。
    """
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.services.document.parse_service import (
        extract_tender_text,
        save_parse_result,
    )
    from app.services.document.parsing.dispatch import parse_tender_multi_agent
    from app.services.document.storage_service import download_file

    logger.info(f"开始解析招标文件: project={project_id}, doc={doc_id}")

    async with async_session_factory() as db:
        from sqlalchemy import select

        result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            return {"status": "error", "message": "文档不存在"}

        doc.status = "parsing"
        await db.flush()

        try:
            file_content = download_file(doc.storage_key)
            text = await extract_tender_text(file_content, doc.title)

            # 多 Agent 并行解析（P1：工具默认关，行为等价旧单次调用）
            parsed = await parse_tender_multi_agent(
                text,
                tools_enabled=False,
                project_id=project_id,
            )

            # 幂等：清理该文档旧评分点 + 旧废标条款后再写入
            # （重复解析/并发 reparse 不产生翻倍数据）
            from sqlalchemy import delete

            from app.models.document import DisqualificationClause, ScorePoint

            doc_uuid = uuid.UUID(doc_id)
            await db.execute(delete(ScorePoint).where(ScorePoint.doc_id == doc_uuid))
            await db.execute(
                delete(DisqualificationClause).where(DisqualificationClause.doc_id == doc_uuid)
            )

            sp_count = await save_parse_result(db, uuid.UUID(project_id), doc_uuid, parsed)

            # 写入 parse_warnings 到 doc.meta（P2 validator 上线后生效）
            if parsed.warnings:
                doc_meta = doc.meta or {}
                doc_meta = {**doc_meta, "parse_warnings": parsed.warnings}
                doc.meta = doc_meta

            from app.models.project import Project

            def _valid_parsed(value: str | None) -> TypeGuard[str]:
                # TypeGuard：调用处据此把 parsed.project_name / tender_no 收窄为 str。
                # 运行时语义：None / 空串 / "mock" 均视为无效，不覆盖库中已有值。
                # 等价于 `bool(value) and value.strip().lower() != "mock"`，但写成早返回，
                # 让 mypy 在第二个 return 前把 `str | None` 收窄为 `str`（若写成单行
                # `bool(value) and ...`，mypy 不会把 bool() 当作类型收窄，会报 union-attr）。
                if not value:
                    return False
                return value.strip().lower() != "mock"

            proj_result = await db.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = proj_result.scalar_one_or_none()
            if project and _valid_parsed(parsed.project_name):
                project.name = parsed.project_name
            if project and _valid_parsed(parsed.tender_no):
                project.tender_no = parsed.tender_no

            await db.commit()

            logger.info(f"解析完成: {sp_count} 评分点")
            return {
                "status": "success",
                "score_points": sp_count,
            }

        except Exception as e:
            doc.status = "failed"
            await db.commit()
            logger.error(f"解析失败: {e}")
            return {"status": "error", "message": str(e)}


async def task_index_document(ctx: dict[str, Any], project_id: str, doc_id: str) -> dict[str, Any]:
    """异步任务：文档向量化入库（RAG 索引）."""
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.services.document.parse_service import extract_tender_text
    from app.services.document.storage_service import download_file
    from app.services.llm.rag_service import (
        chunk_text,
        embed_and_store,
        get_embeddings_batch,
    )

    logger.info(f"开始向量化入库: project={project_id}, doc={doc_id}")

    async with async_session_factory() as db:
        from sqlalchemy import select

        result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            return {"status": "error", "message": "文档不存在"}

        try:
            file_content = download_file(doc.storage_key)
            text = await extract_tender_text(file_content, doc.title)

            chunks = chunk_text(text)
            if not chunks:
                return {"status": "success", "chunks": 0, "message": "无可分块内容"}

            embeddings = await get_embeddings_batch(chunks)
            count = await embed_and_store(db, uuid.UUID(doc_id), chunks, embeddings)

            doc.status = "indexed"
            await db.commit()

            logger.info(f"向量化完成: {count} 个分块")
            return {"status": "success", "chunks": count}

        except Exception as e:
            doc.status = "failed"
            await db.commit()
            logger.error(f"向量化失败: {e}")
            return {"status": "error", "message": str(e)}


async def task_reindex_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """异步任务：重建全部索引（清空 kb_chunks → 重新分块 + Embedding 入库）.

    遍历所有 status='indexed' 的文档，逐个重新分块 + Embedding + 入库。
    用于 Embedding 模型变更后或索引损坏时重建。
    """
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.models.kb_chunk import KbChunk
    from app.services.document.parse_service import extract_tender_text
    from app.services.document.storage_service import download_file
    from app.services.llm.rag_service import (
        chunk_text,
        embed_and_store,
        get_embeddings_batch,
    )

    logger.info("开始重建全部索引")

    async with async_session_factory() as db:
        from sqlalchemy import delete, select

        result = await db.execute(
            select(Document).where(Document.status == "indexed").order_by(Document.created_at)
        )
        docs = result.scalars().all()

        if not docs:
            logger.info("无已索引文档，跳过重建")
            return {"status": "success", "total_docs": 0, "total_chunks": 0}

        await db.execute(delete(KbChunk))
        await db.flush()

        total_chunks = 0
        indexed_docs = 0

        for doc in docs:
            try:
                file_content = download_file(doc.storage_key)
                text = await extract_tender_text(file_content, doc.title)

                chunks = chunk_text(text)
                if not chunks:
                    continue

                embeddings = await get_embeddings_batch(chunks)

                count = await embed_and_store(db, doc.id, chunks, embeddings)
                total_chunks += count
                indexed_docs += 1
                logger.info(f"重建索引: doc={doc.id}, chunks={count}")

            except Exception as e:
                logger.error(f"重建索引失败 doc={doc.id}: {e}")
                continue

        await db.commit()

        logger.info(f"重建完成: {indexed_docs}/{len(docs)} 文档, {total_chunks} 分块")
        return {
            "status": "success",
            "total_docs": indexed_docs,
            "total_chunks": total_chunks,
        }


# 历史注记（P1-2.3）：曾有 task_generate_chapters（arq 入队章节生成），
# 但无任何入队调用方且 start_workflow_in_background 签名演进后已损坏；
# 章节生成统一由 api 层直接调 workflow_runtime（进程内 asyncio 后台执行），已删除收敛。
