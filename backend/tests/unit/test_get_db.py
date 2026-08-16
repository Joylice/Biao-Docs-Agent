"""get_db 事务约定测试（BUG-1 修复）.

约定：get_db 不再代为 commit —— FastAPI 依赖 teardown 在响应发出后才执行，
兜底 commit 导致"注册 200 但用户行尚未提交"的竞态（随后登录 401 等）。
写路径必须在返回响应前显式 ``await db.commit()``；get_db 仅负责异常回滚。
"""

import pytest

from app.core import database


class FakeSession:
    """记录 commit/rollback 调用的桩会话."""

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


@pytest.mark.asyncio
async def test_get_db_does_not_commit_after_yield(monkeypatch) -> None:
    """正常结束：get_db 不代为 commit（写路径自行显式提交）."""
    session = FakeSession()
    monkeypatch.setattr(database, "async_session_factory", lambda: session)

    gen = database.get_db()
    yielded = await gen.__anext__()
    assert yielded is session
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

    assert session.committed == 0, "get_db 兜底 commit 是提交竞态根因，应移除"


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_error(monkeypatch) -> None:
    """业务异常：get_db 回滚并原样上抛，且不 commit."""
    session = FakeSession()
    monkeypatch.setattr(database, "async_session_factory", lambda: session)

    gen = database.get_db()
    await gen.__anext__()
    with pytest.raises(RuntimeError, match="biz error"):
        await gen.athrow(RuntimeError("biz error"))

    assert session.rolled_back == 1
    assert session.committed == 0
