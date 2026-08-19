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
    async def test_list_returns_items(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """成员读取分工列表：含负责人姓名、状态与 outline 子节（2 级目录）."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # _check_project_member（owner 一次即过）
            _join_result([(_assignment(), user, "draft")]),
            _result(None),  # list_assignments 查骨架（无 → 孤儿扁平路径）
        ]
        snapshot = MagicMock()
        snapshot.values = {
            "outline": [{"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]}]
        }

        async def fake_get_state(pid):
            return snapshot

        monkeypatch.setattr(division_api.workflow_runtime, "get_state", fake_get_state)
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["assignee_name"] == "张三"
        assert items[0]["submitted_by_name"] == "张三"
        assert items[0]["status"] == "pending"
        assert items[0]["sections"] == ["背景", "目标"]

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
            _result(None),  # assign_chapters 先查骨架（无嵌套大纲 → 不展开）
            _result(_project()),  # _is_project_member 查 project
            _result(_member_row()),  # 成员表命中
            _result(None),  # 无既有分工
            _join_result([(_assignment(), user, None)]),  # 分配后列表
            _result(None),  # list_assignments 查骨架
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
            _result(None),  # assign_chapters 先查骨架
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


class TestAssistGenerate:
    """阶段 2：AI 辅助生成（可暂停）端点."""

    @pytest.mark.asyncio
    async def test_assist_generate_success(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """assignee 辅助生成：委托 assist_service，返回内容与 stopped 标记 + 审计."""
        from app.services import assist_service

        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        captured: dict = {}

        async def fake_assist(project_id, chapter_no, user_id, prompt="", mode="append"):
            captured["args"] = (chapter_no, prompt, mode)
            return {"content": "辅助生成内容", "stopped": False, "mode": mode}

        monkeypatch.setattr(assist_service, "assist_generate", fake_assist)
        resp = await client.post(
            f"{_url()}/{assignment.id}/assist-generate",
            json={"prompt": "突出安全设计", "mode": "append"},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["content"] == "辅助生成内容"
        assert data["stopped"] is False
        assert captured["args"] == ("1", "突出安全设计", "append")
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_assist_generate_requires_accept(
        self, client: AsyncClient, override_db
    ) -> None:
        """pending 未领取 → 4000."""
        assignment = _assignment("pending")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        resp = await client.post(
            f"{_url()}/{assignment.id}/assist-generate",
            json={},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_assist_generate_forbidden_for_non_assignee(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """非 assignee 成员 → 403."""
        from app.models.project import ProjectMember

        other_member = ProjectMember(project_id=PROJECT_ID, user_id=OTHER_ID)
        assignment = _assignment("in_progress")  # assignee = MEMBER_ID
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),
            _result(other_member),
            _result(assignment),
        ]
        resp = await client.post(
            f"{_url()}/{assignment.id}/assist-generate",
            json={},
            headers=_headers(OTHER_ID),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stop_assist_generate(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """stop 端点：置位取消令牌，返回 stopped=True."""
        from app.services import assist_service

        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        monkeypatch.setattr(assist_service, "stop_task", lambda pid, chapter_no: True)
        resp = await client.post(
            f"{_url()}/{assignment.id}/assist-generate/stop", headers=_headers(MEMBER_ID)
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["stopped"] is True

    @pytest.mark.asyncio
    async def test_stop_without_running_task(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """无进行中任务 → stopped=False（幂等）."""
        from app.services import assist_service

        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [*_member_check_seq(), _result(assignment)]
        monkeypatch.setattr(assist_service, "stop_task", lambda pid, chapter_no: False)
        resp = await client.post(
            f"{_url()}/{assignment.id}/assist-generate/stop", headers=_headers(MEMBER_ID)
        )
        assert resp.json()["data"]["stopped"] is False


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
            _result(_project()),  # 审核通过 → 自动快照钩子加载项目
        ]
        published: list = []

        async def fake_publish(pid, event):
            published.append(event)

        auto_snapshot = AsyncMock(return_value=None)
        monkeypatch.setattr(division_api, "publish_event", fake_publish)
        monkeypatch.setattr(division_api.version_service, "maybe_auto_snapshot", auto_snapshot)
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
        auto_snapshot.assert_awaited_once_with(session, PROJECT_ID, "测试项目")

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


class TestAnnotations:
    """章节批注（阶段 4）：成员可读，assignee/owner 可写."""

    @pytest.mark.asyncio
    async def test_list_returns_items_with_author(self, client: AsyncClient, override_db) -> None:
        """成员读取批注列表：含作者姓名，时间正序."""
        from datetime import UTC, datetime

        from app.models.proposal import ChapterAnnotation

        assignment = _assignment("in_progress")
        ann = ChapterAnnotation(
            project_id=PROJECT_ID,
            chapter_no="1",
            content="补充实施周期说明",
            created_by=MEMBER_ID,
        )
        ann.created_at = datetime.now(UTC)
        session = override_db([])
        session.execute.side_effect = [
            *_member_check_seq(),
            _result(assignment),
            _join_result([(ann, "张三")]),
        ]
        resp = await client.get(
            f"{_url()}/{assignment.id}/annotations", headers=_headers(MEMBER_ID)
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["content"] == "补充实施周期说明"
        assert items[0]["created_by_name"] == "张三"

    @pytest.mark.asyncio
    async def test_create_by_assignee(self, client: AsyncClient, override_db) -> None:
        """assignee 新增批注：落库 + commit."""
        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [
            *_member_check_seq(),
            _result(assignment),
            _result(_project()),  # owner 判定（非 owner）
        ]
        resp = await client.post(
            f"{_url()}/{assignment.id}/annotations",
            headers=_headers(MEMBER_ID),
            json={"content": "需要补充报价明细"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["content"] == "需要补充报价明细"
        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_create_by_owner_allowed(self, client: AsyncClient, override_db) -> None:
        """项目 owner 非 assignee 也可批注."""
        assignment = _assignment("in_progress")
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),  # _check_project_member（owner 一次即过）
            _result(assignment),
            _result(_project()),
        ]
        resp = await client.post(
            f"{_url()}/{assignment.id}/annotations",
            headers=_headers(OWNER_ID),
            json={"content": "owner 批注"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_forbidden_for_other_member(
        self, client: AsyncClient, override_db
    ) -> None:
        """非 assignee 非 owner 成员批注 → 403."""
        other_member = ProjectMember(project_id=PROJECT_ID, user_id=OTHER_ID)
        assignment = _assignment("in_progress")  # assignee = MEMBER_ID
        session = override_db([])
        session.execute.side_effect = [
            _result(_project()),
            _result(other_member),
            _result(assignment),
            _result(_project()),
        ]
        resp = await client.post(
            f"{_url()}/{assignment.id}/annotations",
            headers=_headers(OTHER_ID),
            json={"content": "越权批注"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_forbidden_for_non_member(self, client: AsyncClient, override_db) -> None:
        """非成员读取批注 → 403."""
        override_db([_project(), None])
        resp = await client.get(
            f"{_url()}/{uuid.uuid4()}/annotations", headers=_headers(OTHER_ID)
        )
        assert resp.status_code == 403

