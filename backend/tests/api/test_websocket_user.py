"""用户级 WebSocket 握手鉴权测试 — 阶段 C 工作台实时推送.

契约（与项目级 WS 对齐）：
- /ws/user/{user_id}?token=<JWT access token>
- token 缺失/无效/refresh：close(code=4001)
- token 有效但 sub 与路径 user_id 不一致（订阅他人频道）：close(code=4003)
- 无项目成员校验；通过后进入消息循环（ping → pong）
"""

import uuid

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, create_refresh_token
from app.main import app

USER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def test_user_ws_without_token_closed_4001() -> None:
    """无 token 连接：close(code=4001)."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/user/{USER_ID}"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4001


def test_user_ws_invalid_token_closed_4001() -> None:
    """非法 token：close(code=4001)."""
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/user/{USER_ID}?token=invalid.jwt.token"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4001


def test_user_ws_refresh_token_closed_4001() -> None:
    """refresh token 不能用于 WS 鉴权：close(code=4001)."""
    token = create_refresh_token(str(USER_ID))
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/user/{USER_ID}?token={token}"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4001


def test_user_ws_sub_mismatch_closed_4003() -> None:
    """token 有效但订阅他人频道：close(code=4003)."""
    token = create_access_token(str(OTHER_ID))
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/ws/user/{USER_ID}?token={token}"),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4003


def test_user_ws_invalid_user_id_path_closed_4003() -> None:
    """路径 user_id 非 UUID：close(code=4003)（与项目级非法 project_id 语义一致）."""
    token = create_access_token(str(USER_ID))
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/user/not-a-uuid?token=" + token),
    ):
        pass  # pragma: no cover
    assert exc_info.value.code == 4003


def test_user_ws_ok_and_pong() -> None:
    """本人频道：鉴权通过，ping → pong."""
    token = create_access_token(str(USER_ID))
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/user/{USER_ID}?token={token}") as ws,
    ):
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
