"""工作流重启恢复测试（P1-2.1）.

api 进程重启后，在途 asyncio.create_task 丢失、内存 _running 清空，
DB 中 status=running 残留 → 启动时对账：
- 有 pending interrupt → waiting（图实际停在 HITL，安全可继续）；
- 快照 phase=done → done；
- 其他 → failed（写 error 提示重启中断）。

注意：conftest 已将模块属性 recover_running_workflows 替换为桩，
此处直接调用原始实现 `_recover_running_workflows_impl`。
"""

import uuid
from types import SimpleNamespace

import pytest

from app.models.proposal import ProposalWorkflow
from app.services.infra import workflow_runtime

PROJECT_ID = uuid.uuid4()


def _snapshot(*, interrupt: dict | None = None, phase: str = "generate") -> SimpleNamespace:
    """构造 get_state 返回的最小快照."""
    tasks = ()
    if interrupt is not None:
        tasks = (SimpleNamespace(interrupts=[SimpleNamespace(value=interrupt)]),)
    return SimpleNamespace(values={"current_phase": phase}, tasks=tasks)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """记录 commit 的假 session：execute 返回预置行."""

    def __init__(self, rows):
        self._rows = rows
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _FakeResult(self._rows)

    async def commit(self):
        self.committed = True


def _running_wf() -> ProposalWorkflow:
    return ProposalWorkflow(
        project_id=PROJECT_ID, thread_id=str(PROJECT_ID), status="running", phase="generate"
    )


@pytest.fixture
def saver_ready():
    workflow_runtime._saver = object()  # 非 None 即视为已初始化
    yield
    workflow_runtime._saver = None


async def test_recover_marks_waiting_when_interrupt_pending(monkeypatch, saver_ready) -> None:
    """挂起在 HITL 的 running 残留 → waiting."""
    wf = _running_wf()
    session = _FakeSession([wf])
    monkeypatch.setattr(workflow_runtime, "async_session_factory", lambda: session, raising=False)

    async def fake_get_state(_pid):
        return _snapshot(interrupt={"type": "review_request"})

    monkeypatch.setattr(workflow_runtime, "get_state", fake_get_state)
    await workflow_runtime._recover_running_workflows_impl()
    assert wf.status == "waiting"
    assert session.committed is True


async def test_recover_marks_done_when_phase_done(monkeypatch, saver_ready) -> None:
    """快照 phase=done 的 running 残留 → done."""
    wf = _running_wf()
    session = _FakeSession([wf])
    monkeypatch.setattr(workflow_runtime, "async_session_factory", lambda: session, raising=False)

    async def fake_get_state(_pid):
        return _snapshot(phase="done")

    monkeypatch.setattr(workflow_runtime, "get_state", fake_get_state)
    await workflow_runtime._recover_running_workflows_impl()
    assert wf.status == "done"


async def test_recover_marks_failed_when_in_flight(monkeypatch, saver_ready) -> None:
    """无 interrupt 且未完成的 running 残留 → failed + error 提示."""
    wf = _running_wf()
    session = _FakeSession([wf])
    monkeypatch.setattr(workflow_runtime, "async_session_factory", lambda: session, raising=False)

    async def fake_get_state(_pid):
        return _snapshot(phase="generate")

    monkeypatch.setattr(workflow_runtime, "get_state", fake_get_state)
    await workflow_runtime._recover_running_workflows_impl()
    assert wf.status == "failed"
    assert wf.error and "重启" in wf.error


async def test_recover_skips_when_saver_uninitialized(monkeypatch) -> None:
    """checkpointer 未初始化 → 跳过（不触 DB，避免误标失败）."""
    workflow_runtime._saver = None
    called = {"db": False}

    def _factory():
        called["db"] = True
        return _FakeSession([])

    monkeypatch.setattr(workflow_runtime, "async_session_factory", _factory, raising=False)
    await workflow_runtime._recover_running_workflows_impl()  # 不抛即通过
    assert called["db"] is False


async def test_recover_no_running_rows_noop(monkeypatch, saver_ready) -> None:
    """无 running 残留 → 空转（get_state 不被调用）."""
    session = _FakeSession([])
    monkeypatch.setattr(workflow_runtime, "async_session_factory", lambda: session, raising=False)
    calls = {"n": 0}

    async def fake_get_state(_pid):
        calls["n"] += 1
        return _snapshot()

    monkeypatch.setattr(workflow_runtime, "get_state", fake_get_state)
    await workflow_runtime._recover_running_workflows_impl()
    assert calls["n"] == 0
