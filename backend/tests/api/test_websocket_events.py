"""WebSocket 事件转发测试 — Redis pubsub → WS 前端（SDD §5.4 事件链路）.

链路：nodes.publish_event → Redis 频道 bid:events:{project_id}
→ websocket_endpoint 事件转发循环 → 前端。

- 转发用例使用本地真实 Redis（localhost:6379），频道以随机 project_id 隔离并自清理；
- 降级用例 monkeypatch ``event_service.subscribe_events`` 模拟 Redis 不可用；
- get_status 用例经 ``workflow_runtime.set_saver(InMemorySaver)`` 注入真实状态。
"""

import asyncio
import threading
import time
import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis
from langgraph.checkpoint.memory import InMemorySaver
from starlette.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project
from app.services import event_service, workflow_runtime

OWNER_ID = uuid.uuid4()

RECV_TIMEOUT = 5.0  # 等待服务端转发的上限（秒）


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _owned_project(owner_id: uuid.UUID) -> Project:
    return Project(id=PROJECT_ID, owner_id=owner_id, name="测试项目")


PROJECT_ID = uuid.uuid4()


@pytest.fixture
def member_db() -> Generator:
    """覆盖 get_db：当前用户是项目 owner，鉴权通过."""
    session = AsyncMock()
    session.execute.side_effect = [_result(_owned_project(OWNER_ID))]
    app.dependency_overrides[get_db] = lambda: session
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def member_token() -> str:
    return create_access_token(str(OWNER_ID))


def _wait_for_subscriber(channel: str, timeout: float = 5.0) -> None:
    """轮询 PUBSUB NUMSUB，直到服务端订阅就绪（避免发布早于订阅的竞态）."""
    client = redis.Redis()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # pubsub_numsub 返回 [(channel_bytes, count), ...]，频道名为 bytes
            counts = dict(client.pubsub_numsub(channel))
            if counts.get(channel.encode(), 0) >= 1:
                return
            time.sleep(0.05)
        raise AssertionError(f"等待 WS 服务端订阅频道 {channel} 超时")
    finally:
        client.close()


def _receive_json_with_timeout(ws, timeout: float = RECV_TIMEOUT) -> dict:
    """带超时的 receive_json；超时判失败而不是无限挂起."""
    box: dict = {}

    def _recv() -> None:
        try:
            box["msg"] = ws.receive_json()
        except Exception as e:  # 测试辅助：异常转断言失败
            box["error"] = e

    thread = threading.Thread(target=_recv, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"{timeout}s 内未收到 WS 消息（事件未转发）"
    assert "error" not in box, box.get("error")
    return box["msg"]


def test_ws_forwards_published_event(member_db, member_token) -> None:
    """发布事件到 Redis 频道 → WS 客户端收到原样转发."""
    project_id = uuid.uuid4()  # 随机频道，用例间隔离；pubsub 无持久化即自清理
    event = {"type": "progress", "phase": "outline", "progress": 0.35}
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/{project_id}?token={member_token}") as ws,
    ):
        channel = event_service.event_channel(str(project_id))
        _wait_for_subscriber(channel)

        publisher = redis.Redis()
        try:
            publisher.publish(channel, '{"type": "progress", "phase": "outline", "progress": 0.35}')
        finally:
            publisher.close()

        assert _receive_json_with_timeout(ws) == event


def test_ws_survives_redis_unavailable(member_db, member_token, monkeypatch) -> None:
    """Redis 不可用（订阅抛异常）→ 连接存活，ping 正常 pong（降级而非崩溃）."""

    async def _broken_subscribe(_project_id: str):
        raise ConnectionError("模拟 Redis 不可用")

    monkeypatch.setattr(event_service, "subscribe_events", _broken_subscribe)
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token={member_token}") as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.fixture
def memory_runtime() -> Generator:
    """workflow_runtime 注入 InMemorySaver，用例结束清理."""
    workflow_runtime.set_saver(InMemorySaver())
    yield
    workflow_runtime.set_saver(None)


def test_ws_get_status_returns_checkpointer_state(member_db, member_token, memory_runtime) -> None:
    """get_status 返回 checkpointer 真实状态（替换硬编码 init/0.0）."""
    project_id = uuid.uuid4()
    asyncio.run(
        workflow_runtime.update_state(project_id, {"current_phase": "outline", "progress": 0.35})
    )
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/{project_id}?token={member_token}") as ws,
    ):
        ws.send_json({"type": "get_status"})
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["phase"] == "outline"
        assert status["progress"] == pytest.approx(0.35)


def test_ws_get_status_fallback_when_runtime_uninitialized(member_db, member_token) -> None:
    """runtime 未初始化 → 降级返回旧结构（phase=init, progress=0.0）."""
    workflow_runtime.set_saver(None)
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token={member_token}") as ws,
    ):
        ws.send_json({"type": "get_status"})
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["phase"] == "init"
        assert status["progress"] == 0.0
