"""异步任务入队服务 — arq enqueue 封装（分层铁律：api 层只调用本服务）.

Redis 不可用时记 warning 降级，不阻断上传主流程；
文档状态推进（uploaded→parsing→parsed 等）由 worker 任务负责。
"""

import logging
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _enqueue(job_name: str, project_id: uuid.UUID, doc_id: uuid.UUID) -> bool:
    """入队 arq 任务；Redis 不可用时记 warning 并返回 False（不抛异常）."""
    try:
        from arq import create_pool

        from worker.settings import parse_redis_url

        pool = await create_pool(parse_redis_url(settings.redis_url))
        try:
            await pool.enqueue_job(job_name, str(project_id), str(doc_id))
        finally:
            await pool.aclose()
        return True
    except Exception as e:
        logger.warning("arq 入队失败（降级，不阻断主流程）: job=%s, err=%s", job_name, e)
        return False


async def enqueue_parse_tender(project_id: uuid.UUID, doc_id: uuid.UUID) -> bool:
    """入队招标文件解析任务（worker.tasks.task_parse_tender）."""
    return await _enqueue("task_parse_tender", project_id, doc_id)


async def enqueue_index_document(project_id: uuid.UUID, doc_id: uuid.UUID) -> bool:
    """入队资料库文档向量化任务（worker.tasks.task_index_document）."""
    return await _enqueue("task_index_document", project_id, doc_id)
