"""分工协作 API 测试 — GET/POST /projects/{project_id}/chapter-assignments.

覆盖：
- GET：成员读取分工列表、非成员 403
- POST：owner 分配成功 + 审计 + commit、非 owner 403、assignee 非成员 4004、空列表 4000
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
OTHER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


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


def _join_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


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


class TestListAssignments:
    @pytest.mark.asyncio
    async def test_list_returns_items(self, client: AsyncClient, override_db) -> None:
        """成员读取分工列表：含负责人姓名与状态."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # _check_project_member（owner 一次即过）
            _join_result([(_assignment(), user, "draft")]),
        ]
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["assignee_name"] == "张三"
        assert items[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_forbidden_for_non_member(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.get(_url(), headers=_headers(OTHER_ID))
        assert resp.status_code == 403


class TestAssignChapters:
    @pytest.mark.asyncio
    async def test_assign_succeeds_with_audit_and_commit(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """owner 分配：新建分工 + 审计 division.assign + 推送 task_assigned + commit."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # get_current_owner_id 依赖
            _result(_project()),  # _is_project_member 查 project
            _result(_member_row()),  # 成员表命中
            _result(None),  # 无既有分工
            _join_result([(_assignment(), user, None)]),  # 分配后列表
        ]
        recorded: list = []
        published: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action))

        async def fake_publish(pid, event):
            published.append(event)

        monkeypatch.setattr(division_api, "publish_event", fake_publish)
        with patch.object(division_api.audit, "record", fake_record):
            resp = await client.post(
                _url(),
                headers=_headers(OWNER_ID),
                json=[{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
            )
        assert resp.status_code == 200
        assert recorded == [(OWNER_ID, "division.assign")]
        assert session.commit.await_count == 1
        assert len(published) == 1
        assert published[0]["type"] == "task_assigned"
        assert len(resp.json()["data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_assign_forbidden_for_non_owner(self, client: AsyncClient, override_db) -> None:
        """非 owner 分配 → 403（get_current_owner_id 拦截）."""
        override_db([_project(OTHER_ID)])
        resp = await client.post(
            _url(),
            headers=_headers(MEMBER_ID),
            json=[{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_assign_non_member_assignee_4004(self, client: AsyncClient, override_db) -> None:
        """assignee 非项目成员 → 4004."""
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # get_current_owner_id
            _result(_project()),  # _is_project_member
            _result(None),  # 成员表未命中
        ]
        resp = await client.post(
            _url(),
            headers=_headers(OWNER_ID),
            json=[{"chapter_no": "1", "title": "项目概述", "assignee_id": str(OTHER_ID)}],
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_assign_empty_body_4000(self, client: AsyncClient, override_db) -> None:
        session = override_db([_project()])
        resp = await client.post(_url(), headers=_headers(OWNER_ID), json=[])
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000
        assert session.commit.await_count == 0


def _member_check_seq():
    """成员校验序列：project（非 owner）+ 成员表命中."""
    return [_result(_project()), _result(_member_row())]


class TestAcceptAssignment:
    @pytest.mark.asyncio
    async def test_accept_pending_to_in_progress(self, client: AsyncClient, override_db) -> None:
        """assignee 领取：pending → in_progress + commit."""
        assignment = _assignment("pending")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        resp = await client.post(f"{_url()}/{assignment.id}/accept", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "in_progress"
        assert assignment.status == "in_progress"
        assert assignment.accepted_at is not None
        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_accept_by_non_assignee_forbidden(self, client: AsyncClient, override_db) -> None:
        """非 assignee 领取 → 403."""
        other_member = ProjectMember(project_id=PROJECT_ID, user_id=OTHER_ID)
        assignment = _assignment("pending", assignee_id=MEMBER_ID)
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),
            _result(other_member),
            _result(assignment),
        ]
        resp = await client.post(f"{_url()}/{assignment.id}/accept", headers=_headers(OTHER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_accept_invalid_status_4000(self, client: AsyncClient, override_db) -> None:
        """submitted 状态不可领取 → 4000."""
        assignment = _assignment("submitted")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        resp = await client.post(f"{_url()}/{assignment.id}/accept", headers=_headers(MEMBER_ID))
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000


class TestGenerateAssignment:
    @pytest.mark.asyncio
    async def test_generate_draft_success(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """assignee 生成初稿：调 workflow_runtime 并返回内容."""
        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]

        async def fake_draft(pid, chapter_no):
            return f"章节 {chapter_no} 初稿内容"

        monkeypatch.setattr(division_api.workflow_runtime, "generate_chapter_draft", fake_draft)
        resp = await client.post(f"{_url()}/{assignment.id}/generate", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["content"] == "章节 1 初稿内容"
        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_generate_requires_accept(self, client: AsyncClient, override_db) -> None:
        """pending 未领取 → 4000 请先领取."""
        assignment = _assignment("pending")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        resp = await client.post(f"{_url()}/{assignment.id}/generate", headers=_headers(MEMBER_ID))
        assert resp.status_code == 400
        assert "领取" in resp.json()["message"]


class TestSubmitAssignment:
    @pytest.mark.asyncio
    async def test_submit_publishes_event(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """提交：in_progress → submitted + 推送 task_submitted."""
        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        published: list = []

        async def fake_publish(pid, event):
            published.append((pid, event))

        monkeypatch.setattr(division_api, "publish_event", fake_publish)
        resp = await client.post(f"{_url()}/{assignment.id}/submit", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "submitted"
        assert assignment.submitted_at is not None
        assert len(published) == 1
        assert published[0][1]["type"] == "task_submitted"
        assert published[0][1]["chapter_no"] == "1"

    @pytest.mark.asyncio
    async def test_submit_invalid_status_4000(self, client: AsyncClient, override_db) -> None:
        """pending 不可直接提交 → 4000."""
        assignment = _assignment("pending")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        resp = await client.post(f"{_url()}/{assignment.id}/submit", headers=_headers(MEMBER_ID))
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000


class TestReviewAssignment:
    @pytest.mark.asyncio
    async def test_review_approve_with_event(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """owner 审核通过：submitted → approved + 审计 + 推送 task_reviewed."""
        assignment = _assignment("submitted")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # get_current_owner_id
            _result(assignment),  # get_assignment
        ]
        published: list = []

        async def fake_publish(pid, event):
            published.append(event)

        monkeypatch.setattr(division_api, "publish_event", fake_publish)
        resp = await client.post(
            f"{_url()}/{assignment.id}/review",
            headers=_headers(OWNER_ID),
            json={"action": "approved", "comment": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "approved"
        assert assignment.reviewed_at is not None
        assert session.commit.await_count == 1
        assert published[0]["type"] == "task_reviewed"
        assert published[0]["action"] == "approved"

    @pytest.mark.asyncio
    async def test_review_reject_stores_comment(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """打回：状态 rejected 且意见落库（可重编）."""
        assignment = _assignment("submitted")
        session = override_db([])
        session.execute.side_effect = [_result(_project()), _result(assignment)]

        async def fake_publish(pid, event):
            pass

        monkeypatch.setattr(division_api, "publish_event", fake_publish)
        resp = await client.post(
            f"{_url()}/{assignment.id}/review",
            headers=_headers(OWNER_ID),
            json={"action": "rejected", "comment": "缺少进度计划"},
        )
        assert resp.status_code == 200
        assert assignment.status == "rejected"
        assert assignment.review_comment == "缺少进度计划"

    @pytest.mark.asyncio
    async def test_review_forbidden_for_non_owner(self, client: AsyncClient, override_db) -> None:
        """非 owner 审核 → 403."""
        override_db([_project(OTHER_ID)])
        resp = await client.post(
            f"{_url()}/{uuid.uuid4()}/review",
            headers=_headers(MEMBER_ID),
            json={"action": "approved"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_review_invalid_status_4000(self, client: AsyncClient, override_db) -> None:
        """非 submitted 状态不可审核 → 4000."""
        assignment = _assignment("in_progress")
        override_db([_project(), assignment])
        resp = await client.post(
            f"{_url()}/{assignment.id}/review",
            headers=_headers(OWNER_ID),
            json={"action": "approved"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000
