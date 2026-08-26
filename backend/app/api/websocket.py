"""WebSocket 流式输出 — 对齐 SDD §5.4.

事件链路：agents 节点 publish_event → Redis 频道 bid:events:{project_id}
→ 本端点的事件转发循环 → 前端。两条并发循环：
- 客户端消息循环：ping/pong、get_status（真实 checkpointer 状态）
- 事件转发循环：subscribe_events 订阅 Redis pubsub 并转发
任一循环异常结束即取消另一条（asyncio.TaskGroup）；Redis 不可用时
事件循环降级退出，客户端消息循环继续可用。
"""

import asyncio
import contextlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import BizError
from app.core.security import decode_token
from app.services.infra import event_service, workflow_runtime
from app.services.project.project_service import _check_project_member

logger = logging.getLogger(__name__)

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


async def _current_status(project_id: str) -> dict:
    """get_status 响应体：优先取 checkpointer 真实状态，未初始化时降级旧结构."""
    try:
        return await workflow_runtime.get_status_dict(project_id)
    except Exception:
        logger.debug("checkpointer 状态不可用，降级返回初始状态", exc_info=True)
        return {"phase": "init", "progress": 0.0}


async def _handle_client_messages(websocket: WebSocket, project_id: str) -> None:
    """客户端消息循环：心跳与控制指令（断开时抛 WebSocketDisconnect 结束连接）."""
    while True:
        data = await websocket.receive_text()
        msg = json.loads(data)

        if msg.get("type") == "ping":
            await websocket.send_json({"type": "pong"})
        elif msg.get("type") == "get_status":
            status = await _current_status(project_id)
            await websocket.send_json({"type": "status", **status})


async def _forward_pubsub(websocket: WebSocket, client, pubsub) -> None:
    """pubsub 转发循环：收到事件解析 JSON 后转发前端；退出前清理连接."""
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if message is not None and message.get("type") == "message":
                payload = message.get("data")
                text = payload.decode() if isinstance(payload, bytes) else payload
                await websocket.send_json(json.loads(text))
            else:
                await asyncio.sleep(0.05)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
        with contextlib.suppress(Exception):
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await client.aclose()


async def _forward_redis_events(websocket: WebSocket, project_id: str) -> None:
    """项目事件转发循环；Redis 不可用时记 warning 降级退出（客户端消息循环不受影响）."""
    try:
        client, pubsub = await event_service.subscribe_events(project_id)
    except Exception as e:
        logger.warning("Redis 不可用，事件转发已降级退出: %s", e)
        return
    await _forward_pubsub(websocket, client, pubsub)


async def _forward_user_events(websocket: WebSocket, user_id: str) -> None:
    """用户事件转发循环（阶段 C 工作台推送）；Redis 不可用时降级退出."""
    try:
        client, pubsub = await event_service.subscribe_user_events(user_id)
    except Exception as e:
        logger.warning("Redis 不可用，用户事件转发已降级退出: %s", e)
        return
    await _forward_pubsub(websocket, client, pubsub)


async def _handle_user_messages(websocket: WebSocket) -> None:
    """用户级 WS 客户端消息循环：仅心跳（断开时抛 WebSocketDisconnect）."""
    while True:
        data = await websocket.receive_text()
        msg = json.loads(data)
        if msg.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


async def authenticate_user_websocket(websocket: WebSocket, user_id: str) -> uuid.UUID | None:
    """用户级 WS 握手鉴权：仅校验 token，sub 必须等于路径 user_id（无项目成员校验）.

    - token 缺失/无效 → close(code=4001)
    - 路径 user_id 非法或订阅他人频道 → close(code=4003)
    """
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return None

    sub = payload.get("sub")
    try:
        token_user_id = uuid.UUID(sub) if sub else None
    except ValueError:
        token_user_id = None
    try:
        target_user_id = uuid.UUID(user_id)
    except ValueError:
        target_user_id = None
    if token_user_id is None or target_user_id is None or token_user_id != target_user_id:
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    return token_user_id


@router.websocket("/ws/user/{user_id}")
async def user_websocket_endpoint(websocket: WebSocket, user_id: str) -> None:
    """用户级 WebSocket 端点 — 工作台待办实时推送（阶段 C；握手仅校验 token）."""
    if await authenticate_user_websocket(websocket, user_id) is None:
        return

    await websocket.accept()
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_handle_user_messages(websocket))
            tg.create_task(_forward_user_events(websocket, user_id))
    except* WebSocketDisconnect:
        pass  # 客户端正常断开
    except* Exception:
        logger.warning("用户级 WebSocket 连接异常退出: user_id=%s", user_id, exc_info=True)


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
        # 两条并发循环：任一异常结束（如客户端断开）即取消另一条
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_handle_client_messages(websocket, project_id))
            tg.create_task(_forward_redis_events(websocket, project_id))
    except* WebSocketDisconnect:
        pass  # 客户端正常断开
    except* Exception:
        logger.warning("WebSocket 连接异常退出: project_id=%s", project_id, exc_info=True)
    finally:
        manager.disconnect(project_id)
