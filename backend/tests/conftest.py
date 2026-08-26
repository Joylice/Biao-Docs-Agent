"""conftest — 全局测试 fixture."""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.infra import workflow_runtime

# 测试环境无 PostgreSQL：缩短 checkpointer 连接池等待，避免 TestClient lifespan 阻塞 30s；
# Windows ProactorEventLoop 下 psycopg 不可用，直接短路初始化避免连接重试噪音
# （注意不能用 shutdown_checkpointer 做桩，它会抹掉测试注入的 InMemorySaver）。
settings.workflow_pool_timeout = 0.5


async def _skip_checkpointer_init() -> None:
    """测试桩：跳过 checkpointer 初始化（无 PostgreSQL）."""


# 保留原实现供需要测试 init_checkpointer 自身行为的用例调用
workflow_runtime._init_checkpointer_impl = workflow_runtime.init_checkpointer  # type: ignore[attr-defined]
workflow_runtime.init_checkpointer = _skip_checkpointer_init  # type: ignore[method-assign]


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """为整个测试会话创建事件循环."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """异步测试客户端."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
