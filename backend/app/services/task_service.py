"""异步任务入队服务 — arq enqueue 封装（分层铁律：api 层只调用本服务）.

Redis 不可用时记 warning 降级，不阻断上传主流程；
文档状态推进（uploaded→parsing→parsed 等）由 worker 任务负责。
"""

import logging
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _enqueue(
    job_name: str, project_id: uuid.UUID | None, doc_id: uuid.UUID, **job_kwargs
) -> bool:
    """入队 arq 任务；Redis 不可用时记 warning 并返回 False（不抛异常）."""
    try:
        from arq import create_pool

        from worker.settings import parse_redis_url

        pool = await create_pool(parse_redis_url(settings.redis_url))
        try:
            # project_id 为空 = 全局资料库文档（worker 按 doc_id 定位，不依赖 project）
            await pool.enqueue_job(
                job_name, str(project_id) if project_id else "", str(doc_id), **job_kwargs
            )
        finally:
            await pool.aclose()
        return True
    except Exception as e:
        logger.warning("arq 入队失败（降级，不阻断主流程）: job=%s, err=%s", job_name, e)
        return False


async def enqueue_parse_tender(
    project_id: uuid.UUID, doc_id: uuid.UUID, score_points_only: bool = False
) -> bool:
    """入队招标文件解析任务（worker.tasks.task_parse_tender）.

    score_points_only=True（重新解析场景）：只提取评分点，跳过技术需求提取。
    """
    return await _enqueue(
        "task_parse_tender", project_id, doc_id, score_points_only=score_points_only
    )


async def enqueue_index_document(project_id: uuid.UUID | None, doc_id: uuid.UUID) -> bool:
    """入队资料库文档向量化任务（worker.tasks.task_index_document）.

    project_id 可空：全局资料库（kb_material 独立管理）传 None。
    """
    return await _enqueue("task_index_document", project_id, doc_id)
