"""WebSocket 流式输出 — 对齐 SDD §5.4."""

import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import BizError
from app.core.security import decode_token
from app.services.project_service import _check_project_member

router = APIRouter()

WS_CLOSE_UNAUTHORIZED = 4001  # token 缺失/无效（与 BizError 4001 语义对齐）
WS_CLOSE_FORBIDDEN = 4003  # 已认证但非项目成员（与 BizError 4003 语义对齐）


class ConnectionManager:
    """WebSocket 连接管理器."""

    def __init__(self) -> None:
        """初始化."""
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, project_id: str) -> None:
        """接受连接."""
        await websocket.accept()
        self.active_connections[project_id] = websocket

    def disconnect(self, project_id: str) -> None:
        """断开连接."""
        self.active_connections.pop(project_id, None)

    async def send_progress(self, project_id: str, data: dict) -> None:
        """发送进度消息."""
        ws = self.active_connections.get(project_id)
        if ws:
            await ws.send_json(data)


manager = ConnectionManager()


async def authenticate_websocket(
    websocket: WebSocket, project_id: str, db: AsyncSession
) -> uuid.UUID | None:
    """握手阶段鉴权：query token + 项目成员校验.

    契约（与前端对齐）：
    - token 从 query 参数读取：/ws/{project_id}?token=<JWT access token>
    - token 缺失/无效 → close(code=4001)；非项目成员 → close(code=4003)
    - 校验失败不发送任何业务消息，返回 None；通过则返回用户 ID
    """
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return None

    sub = payload.get("sub")
    try:
        user_id = uuid.UUID(sub) if sub else None
    except ValueError:
        user_id = None
    if user_id is None:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return None

    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        # project_id 非法等价于项目不存在，与 _check_project_member 语义一致
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    try:
        await _check_project_member(db, pid, user_id)
    except BizError:
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    return user_id


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """WebSocket 端点 — 推送工作流进度（握手阶段鉴权）."""
    if await authenticate_websocket(websocket, project_id, db) is None:
        return

    await manager.connect(websocket, project_id)
    try:
        while True:
            # 接收客户端消息（如心跳、控制指令）
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg.get("type") == "get_status":
                # TODO: 从 checkpointer 获取状态
                await websocket.send_json(
                    {
                        "type": "status",
                        "phase": "init",
                        "progress": 0.0,
                    }
                )

    except WebSocketDisconnect:
        manager.disconnect(project_id)
    except Exception:
        manager.disconnect(project_id)


async def stream_generation_progress(project_id: str, events: AsyncGenerator[dict, None]) -> None:
    """流式推送生成进度到前端."""
    async for event in events:
        await manager.send_progress(project_id, event)
