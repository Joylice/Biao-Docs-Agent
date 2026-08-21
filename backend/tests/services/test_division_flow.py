"""division_service 状态机与批注下沉测试 — 批次 1c.

覆盖 api/division.py 下沉的状态转换（领取/提交/审核语义逐条等价）、
项目载入、批注列表/创建（assignee/owner 权限）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ForbiddenError, ValidationError
from app.models.project import Project
from app.models.proposal import ChapterAnnotation, ChapterAssignment
from app.services import division_service

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _join_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _session(seq: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = seq
    session.add = MagicMock()
    return session


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _assignment(status: str = "pending", assignee_id: uuid.UUID = MEMBER_ID) -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no="1",
        title="项目概述",
        assignee_id=assignee_id,
        assigned_by=OWNER_ID,
        status=status,
    )


class TestGetProject:
    @pytest.mark.asyncio
    async def test_returns_project(self) -> None:
        project = _project()
        got = await division_service.get_project(_session([_result(project)]), PROJECT_ID)
        assert got is project

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self) -> None:
        assert await division_service.get_project(_session([_result(None)]), PROJECT_ID) is None


class TestAcceptAssignment:
    @pytest.mark.asyncio
    async def test_pending_to_in_progress(self) -> None:
        assignment = _assignment("pending")
        session = _session([])
        await division_service.accept_assignment(session, assignment)
        assert assignment.status == "in_progress"
        assert assignment.accepted_at is not None
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejected_can_accept(self) -> None:
        """打回后可编辑可重新领取."""
        assignment = _assignment("rejected")
        await division_service.accept_assignment(_session([]), assignment)
        assert assignment.status == "in_progress"

    @pytest.mark.asyncio
    async def test_submitted_cannot_accept(self) -> None:
        assignment = _assignment("submitted")
        with pytest.raises(ValidationError) as exc:
            await division_service.accept_assignment(_session([]), assignment)
        assert "当前状态 submitted 不可领取" in str(exc.value.message)


class TestSubmitAssignment:
    @pytest.mark.asyncio
    async def test_in_progress_to_submitted(self) -> None:
        assignment = _assignment("in_progress")
        session = _session([])
        await division_service.submit_assignment(session, assignment)
        assert assignment.status == "submitted"
        assert assignment.submitted_at is not None
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejected_can_submit(self) -> None:
        assignment = _assignment("rejected")
        await division_service.submit_assignment(_session([]), assignment)
        assert assignment.status == "submitted"

    @pytest.mark.asyncio
    async def test_pending_cannot_submit(self) -> None:
        assignment = _assignment("pending")
        with pytest.raises(ValidationError) as exc:
            await division_service.submit_assignment(_session([]), assignment)
        assert "当前状态 pending 不可提交" in str(exc.value.message)


class TestReviewAssignment:
    @pytest.mark.asyncio
    async def test_submitted_to_approved(self) -> None:
        assignment = _assignment("submitted")
        session = _session([])
        await division_service.review_assignment(session, assignment, "approved", "")
        assert assignment.status == "approved"
        assert assignment.review_comment is None, "空意见不落库"
        assert assignment.reviewed_at is not None
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submitted_to_rejected_with_comment(self) -> None:
        assignment = _assignment("submitted")
        await division_service.review_assignment(
            _session([]), assignment, "rejected", "缺少进度计划"
        )
        assert assignment.status == "rejected"
        assert assignment.review_comment == "缺少进度计划"

    @pytest.mark.asyncio
    async def test_non_submitted_cannot_review(self) -> None:
        assignment = _assignment("in_progress")
        with pytest.raises(ValidationError) as exc:
            await division_service.review_assignment(_session([]), assignment, "approved", "")
        assert "当前状态 in_progress 不可审核" in str(exc.value.message)


class TestAssignmentAnnotations:
    @pytest.mark.asyncio
    async def test_list_annotations_serializes_author(self) -> None:
        ann = ChapterAnnotation(
            project_id=PROJECT_ID,
            chapter_no="1",
            content="补充说明",
            created_by=MEMBER_ID,
        )
        ann.created_at = datetime.now(UTC)
        session = _session([_join_result([(ann, "张三")])])
        items = await division_service.list_annotations(session, PROJECT_ID, "1")
        assert items[0]["content"] == "补充说明"
        assert items[0]["created_by_name"] == "张三"
        assert items[0]["created_by"] == str(MEMBER_ID)
        assert items[0]["created_at"] is not None

    @pytest.mark.asyncio
    async def test_create_annotation_by_assignee(self) -> None:
        assignment = _assignment("in_progress")
        session = _session([_result(_project())])  # owner 判定（非 owner）
        ann = await division_service.create_annotation(
            session, PROJECT_ID, assignment, " 需要补充报价明细 ", MEMBER_ID
        )
        assert ann.content == "需要补充报价明细", "内容去首尾空格"
        assert ann.chapter_no == "1"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_annotation_by_owner(self) -> None:
        assignment = _assignment("in_progress")
        session = _session([_result(_project())])  # owner 判定（是 owner）
        ann = await division_service.create_annotation(
            session, PROJECT_ID, assignment, "owner 批注", OWNER_ID
        )
        assert ann.created_by == OWNER_ID

    @pytest.mark.asyncio
    async def test_create_annotation_forbidden_for_other(self) -> None:
        assignment = _assignment("in_progress")  # assignee = MEMBER_ID
        other_id = uuid.uuid4()
        session = _session([_result(_project())])  # owner 判定（非 owner）
        with pytest.raises(ForbiddenError):
            await division_service.create_annotation(
                session, PROJECT_ID, assignment, "越权批注", other_id
            )
