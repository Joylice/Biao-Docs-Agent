"""event_service 用户级事件测试 — 阶段 C（频道命名 + 发布 + 订阅）."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import event_service


def test_user_event_channel_naming() -> None:
    """用户频道命名契约：bid:user:{user_id}."""
    assert event_service.user_event_channel("u-123") == "bid:user:u-123"


@pytest.mark.asyncio
async def test_publish_user_event_to_user_channel() -> None:
    """publish_user_event 发布到用户频道（JSON 序列化）."""
    client = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=client):
        await event_service.publish_user_event("u-1", {"type": "workbench_refresh"})
    client.publish.assert_awaited_once()
    channel, payload = client.publish.call_args.args[:2]
    assert channel == "bid:user:u-1"
    assert '"type": "workbench_refresh"' in payload
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_user_event_degrades_silently() -> None:
    """Redis 不可用时静默降级（不抛异常，不影响主流程）."""
    with patch("redis.asyncio.from_url", side_effect=ConnectionError("no redis")):
        await event_service.publish_user_event("u-1", {"type": "task_assigned"})


@pytest.mark.asyncio
async def test_subscribe_user_events_subscribes_user_channel() -> None:
    """subscribe_user_events 订阅用户频道并返回 (client, pubsub)."""
    client = AsyncMock()
    pubsub = AsyncMock()
    # pubsub() 在 redis client 上是同步方法
    client.pubsub = MagicMock(return_value=pubsub)
    with patch("redis.asyncio.from_url", return_value=client):
        got_client, got_pubsub = await event_service.subscribe_user_events("u-9")
    assert got_client is client and got_pubsub is pubsub
    pubsub.subscribe.assert_awaited_once_with("bid:user:u-9")
