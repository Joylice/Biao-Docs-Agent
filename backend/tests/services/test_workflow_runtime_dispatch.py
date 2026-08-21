"""workflow_runtime 下沉函数测试 — 批次 1c：成员 ID 收集与审阅意见回派.

redispatch_feedback 语义等价自 api/workflow.py 原 _redispatch_feedback：
命中分工 → rejected + 事件收集；子节降级父章；无分工保留 rewrite；
仅 flush 不 commit（提交由 api 层在 resume 前执行）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.proposal import ChapterAssignment
from app.services import workflow_runtime

PROJECT_ID = uuid.uuid4()
ASSIGNEE_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _session(seq: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = seq
    session.add = MagicMock()
    return session


def _assignment(chapter_no: str = "1") -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no=chapter_no,
        title="项目概述",
        assignee_id=ASSIGNEE_ID,
        assigned_by=uuid.uuid4(),
        status="approved",
    )


def _fake_get_state(outline: list):
    async def fake(pid):
        snapshot = MagicMock()
        snapshot.values = {"outline": outline}
        return snapshot

    return fake


class TestListProjectMemberIds:
    @pytest.mark.asyncio
    async def test_returns_member_user_ids(self) -> None:
        uid1, uid2 = uuid.uuid4(), uuid.uuid4()
        session = _session([_scalars_result([uid1, uid2])])
        ids = await workflow_runtime.list_project_member_ids(session, PROJECT_ID)
        assert ids == [uid1, uid2]


class TestRedispatchFeedback:
    @pytest.mark.asyncio
    async def test_empty_feedback_noop(self) -> None:
        session = _session([])
        remaining, events = await workflow_runtime.redispatch_feedback(session, PROJECT_ID, {})
        assert remaining == {}
        assert events == []
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hit_assignment_rejected_and_event(self, monkeypatch) -> None:
        """编号命中分工：打回 + 意见落库 + 收集 task_reviewed 事件（不推送）."""
        monkeypatch.setattr(
            workflow_runtime,
            "get_state",
            _fake_get_state([{"chapter_no": "1", "title": "项目概述"}]),
        )
        assignment = _assignment("1")
        session = _session([_result(assignment)])
        remaining, events = await workflow_runtime.redispatch_feedback(
            session, PROJECT_ID, {"1": "缺少进度计划"}
        )
        assert remaining == {}
        assert assignment.status == "rejected"
        assert assignment.review_comment == "缺少进度计划"
        assert assignment.reviewed_at is not None
        assert events == [
            {
                "type": "task_reviewed",
                "chapter_no": "1",
                "assignee_id": str(ASSIGNEE_ID),
                "action": "rejected",
            }
        ]
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_title_key_matches_chapter(self, monkeypatch) -> None:
        """标题键匹配章节 → 同样回派."""
        monkeypatch.setattr(
            workflow_runtime,
            "get_state",
            _fake_get_state([{"chapter_no": "2", "title": "技术方案"}]),
        )
        assignment = _assignment("2")
        session = _session([_result(assignment)])
        remaining, events = await workflow_runtime.redispatch_feedback(
            session, PROJECT_ID, {"技术方案": "补充架构图"}
        )
        assert remaining == {}
        assert assignment.status == "rejected"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_subsection_falls_back_to_parent(self, monkeypatch) -> None:
        """子节无分工 → 降级回派父章负责人（章级分工覆盖子节）."""
        monkeypatch.setattr(
            workflow_runtime,
            "get_state",
            _fake_get_state(
                [{"chapter_no": "1", "title": "项目概述", "sections": [{"title": "项目背景"}]}]
            ),
        )
        parent = _assignment("1")
        session = _session([_result(None), _result(parent)])
        remaining, events = await workflow_runtime.redispatch_feedback(
            session, PROJECT_ID, {"1.1": "细化背景"}
        )
        assert remaining == {}
        assert parent.status == "rejected"
        assert events[0]["chapter_no"] == "1.1", "事件仍带子节编号"

    @pytest.mark.asyncio
    async def test_no_assignment_keeps_rewrite(self, monkeypatch) -> None:
        """无分工章节 → 意见保留在 remaining（原 rewrite 链路）."""
        monkeypatch.setattr(
            workflow_runtime,
            "get_state",
            _fake_get_state([{"chapter_no": "3", "title": "实施计划"}]),
        )
        session = _session([_result(None)])
        remaining, events = await workflow_runtime.redispatch_feedback(
            session, PROJECT_ID, {"3": "细化里程碑"}
        )
        assert remaining == {"3": "细化里程碑"}
        assert events == []

    @pytest.mark.asyncio
    async def test_unknown_key_keeps_rewrite(self, monkeypatch) -> None:
        """编号/标题均未命中大纲 → 保留在 remaining."""
        monkeypatch.setattr(workflow_runtime, "get_state", _fake_get_state([]))
        session = _session([])
        remaining, events = await workflow_runtime.redispatch_feedback(
            session, PROJECT_ID, {"9": "x"}
        )
        assert remaining == {"9": "x"}
        assert events == []
