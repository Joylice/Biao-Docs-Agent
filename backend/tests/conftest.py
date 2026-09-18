"""conftest — 全局测试 fixture."""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.infra import settings_service
from app.services.infra import workflow_runtime as wf_facade
from app.services.infra.workflow import runtime as wf_runtime

# 测试环境无 PostgreSQL：缩短 checkpointer 连接池等待，避免 TestClient lifespan 阻塞 30s；
# Windows ProactorEventLoop 下 psycopg 不可用，直接短路初始化避免连接重试噪音
# （注意不能用 shutdown_checkpointer 做桩，它会抹掉测试注入的 InMemorySaver）。
settings.workflow_pool_timeout = 0.5
# 测试环境固定非默认密钥：本地 .env 若为生产形态（debug=False+非 mock）+默认密钥，
# 启动防护会拒绝 lifespan 启动（P0-1.3），测试统一覆盖保证稳定。
settings.jwt_secret = "test-only-secret"
settings.minio_secret_key = "test-only-secret"


async def _skip_checkpointer_init() -> None:
    """测试桩：跳过 checkpointer 初始化（无 PostgreSQL）."""


# 保留原实现供需要测试 init_checkpointer 自身行为的用例调用
wf_runtime._init_checkpointer_impl = wf_runtime.init_checkpointer  # type: ignore[attr-defined]


async def _skip_workflow_recovery() -> dict:
    """测试桩：跳过启动期工作流对账（无 PostgreSQL，且避免误改共享单例状态）."""
    return {}


wf_runtime._recover_running_workflows_impl = wf_runtime.recover_running_workflows  # type: ignore[attr-defined]

# 桩必须打在**外层门面**（`app.services.infra.workflow_runtime`）上：
# `app/main.py` 的 lifespan 走的是 `from app.services.infra import workflow_runtime`，
# 而门面属性在导入期已绑定为原函数对象 —— 只改内层 `workflow.runtime` 改不到它
# （实测 `outer.init_checkpointer is _skip` 为 False，真实实现照跑：
#  日志里 `runtime.py 工作流 checkpointer 初始化失败` 即由此产生）。
# 两层都打，保证无论调用方从哪一层取都能短路。
for _mod in (wf_facade, wf_runtime):
    _mod.init_checkpointer = _skip_checkpointer_init  # type: ignore[method-assign]
    _mod.recover_running_workflows = _skip_workflow_recovery  # type: ignore[method-assign]


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


@pytest.fixture(autouse=True)
def _clean_settings_facade_bindings() -> Generator[None, None, None]:
    """清理 settings_service 门面 __dict__ 残留的静态绑定.

    存量测试用字符串路径 patch（``monkeypatch.setattr(
    "app.services.infra.settings_service.X", ...)``）时，pytest undo 阶段以
    ``setattr`` 恢复旧值，会在门面 ``__dict__`` 残留静态绑定，遮蔽 PEP 562
    ``__getattr__`` 动态转发，导致后续对 runtime/storage 子模块的 patch 不生效。
    autouse 先于测试内 monkeypatch setup（teardown 逆序 = monkeypatch 先 undo，
    本 fixture 后清理），保证残留被删除、门面恢复纯动态转发。
    """
    yield
    for name in list(settings_service.__dict__):
        if name in settings_service._SYMBOL_SOURCE:  # type: ignore[attr-defined]
            del settings_service.__dict__[name]
