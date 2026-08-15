"""WebSocket 握手鉴权测试 — query token 方案（security.md §3，IDOR 修复）.

与前端智能体对齐的契约：
- 握手阶段从 query 参数读取 token：/ws/{project_id}?token=<JWT access token>
- token 无效/缺失：close(code=4001)；已认证但非项目成员：close(code=4003)
- 校验失败不发送任何业务消息

说明：测试环境无可用 PostgreSQL，成员校验的 DB 结果经
``app.dependency_overrides[get_db]`` + mock 会话注入，鉴权链路为真实执行。
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.main import app
from app.models.project import Project

OWNER_ID = uuid.uuid4()
OUTSIDER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _mock_session(scalar_sequence: list) -> AsyncMock:
    """mock 会话：按顺序为每次 execute 返回预设标量结果."""
    session = AsyncMock()
    session.execute.side_effect = [_result(s) for s in scalar_sequence]
    return session


def _owned_project(owner_id: uuid.UUID) -> Project:
    return Project(id=PROJECT_ID, owner_id=owner_id, name="测试项目")


@pytest.fixture
def override_db() -> Generator:
    """按预设结果序列覆盖 get_db，用例结束清理."""

    def _override(scalar_sequence: list) -> AsyncMock:
        session = _mock_session(scalar_sequence)
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def test_ws_connect_without_token_closed_4001() -> None:
    """无 token 连接：close(code=4001)，不发送任何业务消息."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/{PROJECT_ID}"),
    ):
        pass  # pragma: no cover — 不应进入消息循环
    assert exc_info.value.code == 4001


def test_ws_connect_with_invalid_token_closed_4001() -> None:
    """伪造/非法 token：close(code=4001)."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token=invalid.jwt.token"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4001


def test_ws_connect_with_refresh_token_closed_4001() -> None:
    """refresh token 不能用于 WS 鉴权：close(code=4001)."""
    token = create_refresh_token(str(OWNER_ID))
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token={token}"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4001


def test_ws_connect_as_non_member_closed_4003(override_db) -> None:
    """已认证但非项目成员：close(code=4003)，不发送任何业务消息."""
    override_db([_owned_project(OWNER_ID), None])
    token = create_access_token(str(OUTSIDER_ID))
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token={token}"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4003


def test_ws_connect_as_member_ok_and_pong(override_db) -> None:
    """项目成员（owner）：鉴权通过，进入正常消息循环（ping → pong）."""
    override_db([_owned_project(OWNER_ID)])
    token = create_access_token(str(OWNER_ID))
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/{PROJECT_ID}?token={token}") as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
