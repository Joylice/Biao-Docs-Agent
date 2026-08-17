"""异步任务定义 — Arq worker 执行."""

import logging
import uuid

logger = logging.getLogger(__name__)


async def task_parse_tender(
    ctx: dict, project_id: str, doc_id: str, score_points_only: bool = False
) -> dict:
    """异步任务：解析招标文件.

    score_points_only=True（重新解析入队）：只提取评分点，跳过技术需求提取。
    """
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.services.parse_service import (
        extract_tender_text,
        parse_tender_with_llm,
        save_parse_result,
    )
    from app.services.storage_service import download_file

    logger.info(f"开始解析招标文件: project={project_id}, doc={doc_id}")

    async with async_session_factory() as db:
        # 获取文档记录
        from sqlalchemy import select

        result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            return {"status": "error", "message": "文档不存在"}

        # 更新状态为 parsing
        doc.status = "parsing"
        await db.flush()

        try:
            # 下载文件
            file_content = download_file(doc.storage_key)

            # 提取文本
            text = await extract_tender_text(file_content, doc.title)

            # LLM 解析（重新解析场景跳过技术需求提取）
            parsed = await parse_tender_with_llm(
                text, include_tech_requirements=not score_points_only
            )

            # 保存结果
            sp_count, tr_count = await save_parse_result(
                db, uuid.UUID(project_id), uuid.UUID(doc_id), parsed
            )

            # 更新项目信息（空值或 mock 占位值不覆盖，避免污染真实项目名/编号）
            from app.models.project import Project

            def _valid_parsed(value: str | None) -> bool:
                return bool(value) and value.strip().lower() != "mock"

            proj_result = await db.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = proj_result.scalar_one_or_none()
            if project and _valid_parsed(parsed.project_name):
                project.name = parsed.project_name
            if project and _valid_parsed(parsed.tender_no):
                project.tender_no = parsed.tender_no

            await db.commit()

            logger.info(f"解析完成: {sp_count} 评分点, {tr_count} 技术需求")
            return {
                "status": "success",
                "score_points": sp_count,
                "tech_requirements": tr_count,
            }

        except Exception as e:
            doc.status = "failed"
            await db.commit()
            logger.error(f"解析失败: {e}")
            return {"status": "error", "message": str(e)}


async def task_index_document(ctx: dict, project_id: str, doc_id: str) -> dict:
    """异步任务：文档向量化入库（RAG 索引）."""
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.services.parse_service import extract_tender_text
    from app.services.rag_service import (
        chunk_text,
        embed_and_store,
        get_embeddings_batch,
    )
    from app.services.storage_service import download_file

    logger.info(f"开始向量化入库: project={project_id}, doc={doc_id}")

    async with async_session_factory() as db:
        from sqlalchemy import select

        result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            return {"status": "error", "message": "文档不存在"}

        try:
            # 下载并提取文本
            file_content = download_file(doc.storage_key)
            text = await extract_tender_text(file_content, doc.title)

            # 分块
            chunks = chunk_text(text)
            if not chunks:
                return {"status": "success", "chunks": 0, "message": "无可分块内容"}

            # 批量 Embedding
            embeddings = await get_embeddings_batch(chunks)

            # 入库
            count = await embed_and_store(db, uuid.UUID(doc_id), chunks, embeddings)

            # 更新文档状态
            doc.status = "indexed"
            await db.commit()

            logger.info(f"向量化完成: {count} 个分块")
            return {"status": "success", "chunks": count}

        except Exception as e:
            doc.status = "failed"
            await db.commit()
            logger.error(f"向量化失败: {e}")
            return {"status": "error", "message": str(e)}


async def task_generate_chapters(ctx: dict, project_id: str) -> dict:
    """异步任务：逐章生成方案内容."""
    logger.info(f"开始章节生成: project={project_id}")

    # TODO: 接入 LangGraph workflow 执行
    # 目前由 workflow API 同步处理
    return {"status": "success", "message": "章节生成任务已提交"}
