"""division_service 单元测试 — 分配 upsert、列表、章节级编辑权限.

DB 会话以 AsyncMock + execute 序列模拟（与 API 测试同模式）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAssignment
from app.models.user import User
from app.services import division_service

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _session(seq: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = seq
    session.add = MagicMock()
    return session


class TestAssignChapters:
    @pytest.mark.asyncio
    async def test_assign_new_chapter_adds_pending(self) -> None:
        """新分配：add + flush，状态 pending."""
        session = _session(
            [
                _result(_project()),  # _is_project_member 查 project
                _result(_member_row()),  # 成员表命中
                _result(None),  # 无既有分工
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
        )
        assert len(assignments) == 1
        assert assignments[0].status == "pending"
        assert assignments[0].assignee_id == MEMBER_ID
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_assign_existing_resets_status(self) -> None:
        """幂等 upsert：既有分工更新负责人并重置流转状态."""
        existing = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="旧标题",
            assignee_id=OTHER_ID,
            assigned_by=OWNER_ID,
            status="submitted",
            review_comment="旧意见",
        )
        session = _session(
            [
                _result(_project()),
                _result(_member_row()),
                _result(existing),
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "新标题", "assignee_id": str(MEMBER_ID)}],
        )
        updated = assignments[0]
        assert updated is existing
        assert updated.status == "pending"
        assert updated.assignee_id == MEMBER_ID
        assert updated.title == "新标题"
        assert updated.review_comment is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_non_member_raises_4004(self) -> None:
        """assignee 非项目成员 → 4004."""
        session = _session(
            [
                _result(_project()),  # owner 判定不通过（OTHER 非 owner）
                _result(None),  # 成员表未命中
            ]
        )
        with pytest.raises(BizError) as exc:
            await division_service.assign_chapters(
                session,
                PROJECT_ID,
                OWNER_ID,
                [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(OTHER_ID)}],
            )
        assert exc.value.code == 4004

    @pytest.mark.asyncio
    async def test_assign_missing_fields_raises_4000(self) -> None:
        session = _session([])
        with pytest.raises(BizError) as exc:
            await division_service.assign_chapters(
                session, PROJECT_ID, OWNER_ID, [{"chapter_no": "1"}]
            )
        assert exc.value.code == 4000


class TestListAssignments:
    @pytest.mark.asyncio
    async def test_list_includes_assignee_name_and_section_status(self) -> None:
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        assignment = ChapterAssignment(
            id=uuid.uuid4(),
            project_id=PROJECT_ID,
            chapter_no="1",
            title="项目概述",
            assignee_id=MEMBER_ID,
            assigned_by=OWNER_ID,
            status="in_progress",
        )
        join_result = MagicMock()
        join_result.all.return_value = [(assignment, user, "draft")]
        session = _session([join_result])

        items = await division_service.list_assignments(session, PROJECT_ID)
        assert len(items) == 1
        assert items[0]["assignee_name"] == "张三"
        assert items[0]["status"] == "in_progress"
        assert items[0]["section_status"] == "draft"
        assert items[0]["chapter_no"] == "1"


class TestCheckChapterEditable:
    @pytest.mark.asyncio
    async def test_unassigned_chapter_editable(self) -> None:
        """未分配章节保持现状（项目成员可编辑）."""
        session = _session([_result(None)])
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "9", OTHER_ID)

    @pytest.mark.asyncio
    async def test_assignee_editable(self) -> None:
        assignment = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="t",
            assignee_id=MEMBER_ID,
            assigned_by=OWNER_ID,
        )
        session = _session([_result(assignment)])
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1", MEMBER_ID)

    @pytest.mark.asyncio
    async def test_owner_editable(self) -> None:
        assignment = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="t",
            assignee_id=MEMBER_ID,
            assigned_by=OWNER_ID,
        )
        session = _session([_result(assignment)])
        assert await division_service.check_chapter_editable(
            session, PROJECT_ID, "1", OWNER_ID, is_owner=True
        )

    @pytest.mark.asyncio
    async def test_other_member_not_editable(self) -> None:
        """已分配章节：非 assignee 且非 owner → 不可编辑（可视不可改）."""
        assignment = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="t",
            assignee_id=MEMBER_ID,
            assigned_by=OWNER_ID,
        )
        session = _session([_result(assignment), _result(_project())])
        assert not await division_service.check_chapter_editable(session, PROJECT_ID, "1", OTHER_ID)

    @pytest.mark.asyncio
    async def test_owner_fallback_editable(self) -> None:
        """未传 is_owner 时 owner 经兜底查询仍可编辑."""
        assignment = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="t",
            assignee_id=MEMBER_ID,
            assigned_by=OWNER_ID,
        )
        session = _session([_result(assignment), _result(_project())])
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1", OWNER_ID)
