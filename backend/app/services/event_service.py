"""事件发布服务 — worker 执行进度经 Redis pub/sub 推送，供 WebSocket 转发前端."""

import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# 事件类型协议（前后端统一）：
# progress      {"type":"progress","phase":...,"progress":...,"current_chapter":...}
# section_token {"type":"section_token","chapter_no":...,"delta":...}
# section_done  {"type":"section_done","chapter_no":...}
# task_done     {"type":"task_done","export_storage_key":...}
# error         {"type":"error","message":...}
# task_assigned   {"type":"task_assigned","assignments":[{chapter_no,assignee_id}]}
# task_submitted  {"type":"task_submitted","chapter_no":...,"assignee_id":...,"assignment_id":...}
# task_reviewed   {"type":"task_reviewed","chapter_no":...,"assignee_id":...,"action":...}


def event_channel(project_id: str) -> str:
    """项目事件频道名."""
    return f"bid:events:{project_id}"


async def publish_event(project_id: str, event: dict) -> None:
    """发布事件到 Redis 频道；Redis 不可用时静默降级（不影响主流程）."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        await client.publish(event_channel(project_id), json.dumps(event, ensure_ascii=False))
        await client.aclose()
    except Exception as e:
        logger.warning("事件推送失败（已降级）: %s", e)


async def subscribe_events(project_id: str):
    """订阅项目事件频道（返回 pubsub 对象，由调用方负责取消订阅与关闭）."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(event_channel(project_id))
    return client, pubsub
