"""分工端点用户级事件推送测试 — 阶段 C（工作台待办实时推送）.

契约：
- assign：按 assignee 去重推送 task_assigned 到各自用户频道
- submit：推送 task_submitted 到项目 owner 频道
- review：推送 task_reviewed 到 assignee 频道
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.division as division_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAssignment
from app.models.user import User

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


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _assignment(status: str = "pending") -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no="1",
        title="项目概述",
        assignee_id=MEMBER_ID,
        assigned_by=OWNER_ID,
        status=status,
    )


@pytest.fixture
def override_db() -> Generator:
    def _override(scalar_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = [_result(s) for s in scalar_sequence]
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/chapter-assignments"


class TestAssignPublishesUserEvent:
    @pytest.mark.asyncio
    async def test_assign_pushes_task_assigned_to_assignee(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """分配后向每个 assignee 用户频道推送 task_assigned."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # get_current_owner_id
            _result(None),  # assign_chapters 查骨架
            _result(_project()),  # 成员校验 project
            _result(_member_row()),  # 成员表命中
            _result(None),  # 无既有分工
            _join_result([(_assignment(), user, None)]),  # 分配后列表
            _result(None),  # list_assignments 查骨架
        ]
        user_events: list = []

        async def fake_publish_user(uid, event):
            user_events.append((uid, event))

        async def fake_record(db, user_id, action, **kwargs):
            pass

        monkeypatch.setattr(division_api, "publish_event", AsyncMock())
        monkeypatch.setattr(division_api, "publish_user_event", fake_publish_user)
        with patch.object(division_api.audit, "record", fake_record):
            resp = await client.post(
                _url(),
                headers=_headers(OWNER_ID),
                json=[{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
            )
        assert resp.status_code == 200
        assert len(user_events) == 1
        assert user_events[0][0] == str(MEMBER_ID)
        assert user_events[0][1]["type"] == "task_assigned"


class TestSubmitPublishesOwnerEvent:
    @pytest.mark.asyncio
    async def test_submit_pushes_task_submitted_to_owner(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """提交后向项目 owner 用户频道推送 task_submitted."""
        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # 成员校验 project
            _result(_member_row()),  # 成员表命中
            _result(assignment),  # get_assignment
            _result(_project()),  # 加载项目取 owner_id
        ]
        user_events: list = []

        async def fake_publish_user(uid, event):
            user_events.append((uid, event))

        monkeypatch.setattr(division_api, "publish_event", AsyncMock())
        monkeypatch.setattr(division_api, "publish_user_event", fake_publish_user)
        resp = await client.post(f"{_url()}/{assignment.id}/submit", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert len(user_events) == 1
        assert user_events[0][0] == str(OWNER_ID)
        assert user_events[0][1]["type"] == "task_submitted"
        assert user_events[0][1]["chapter_no"] == "1"


class TestReviewPublishesAssigneeEvent:
    @pytest.mark.asyncio
    async def test_review_pushes_task_reviewed_to_assignee(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """审核后向 assignee 用户频道推送 task_reviewed."""
        assignment = _assignment("submitted")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # get_current_owner_id
            _result(assignment),  # get_assignment
            _result(_project()),  # 审核通过 → 自动快照钩子
        ]
        user_events: list = []

        async def fake_publish_user(uid, event):
            user_events.append((uid, event))

        monkeypatch.setattr(division_api, "publish_event", AsyncMock())
        monkeypatch.setattr(division_api, "publish_user_event", fake_publish_user)
        monkeypatch.setattr(division_api.version_service, "maybe_auto_snapshot", AsyncMock())
        resp = await client.post(
            f"{_url()}/{assignment.id}/review",
            headers=_headers(OWNER_ID),
            json={"action": "approved", "comment": ""},
        )
        assert resp.status_code == 200
        assert len(user_events) == 1
        assert user_events[0][0] == str(MEMBER_ID)
        assert user_events[0][1]["type"] == "task_reviewed"
        assert user_events[0][1]["action"] == "approved"
