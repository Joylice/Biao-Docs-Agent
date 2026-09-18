"""Arq Worker 配置与任务注册."""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import settings
from worker.tasks import task_index_document, task_parse_tender, task_reindex_all


def parse_redis_url(url: str) -> RedisSettings:
    """解析 Redis URL 为 Arq RedisSettings."""
    # redis://localhost:6379/0
    url = url.replace("redis://", "")
    parts = url.split(":")
    host = parts[0]
    port_db = parts[1] if len(parts) > 1 else "6379/0"
    port_parts = port_db.split("/")
    port = int(port_parts[0])
    database = int(port_parts[1]) if len(port_parts) > 1 else 0
    return RedisSettings(host=host, port=port, database=database)


class WorkerSettings:
    """Arq Worker 配置."""

    functions: ClassVar[list[Any]] = [
        task_parse_tender,
        task_index_document,
        task_reindex_all,
    ]
    redis_settings = parse_redis_url(settings.redis_url)
    max_jobs = 10
    job_timeout = 600  # 10 分钟
    retry_jobs = True
    max_tries = 3
