"""项目成员管理 API 测试 — GET/DELETE /projects/{project_id}/members（阶段二）.

覆盖：
- GET：成员列表（owner 恒在首位、字段完整）、非成员 403
- DELETE：owner 移除成功 + 审计 + 显式 commit、非 owner 403、
  移除 owner 4000、自移 4000、目标非成员 404
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.projects as projects_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project, ProjectMember
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


def _user(user_id: uuid.UUID, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="x",
        display_name=f"用户{user_id.hex[:4]}",
        created_at=datetime.now(UTC),
    )


def _member(user_id: uuid.UUID, joined: datetime) -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=user_id, joined_at=joined)


@pytest.fixture
def override_db() -> Generator:
    """按预设 scalar 序列覆盖 get_db，用例结束清理."""

    def _override(scalar_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = [_result(s) for s in scalar_sequence]
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


class TestListMembers:
    """GET /projects/{project_id}/members."""

    @pytest.mark.asyncio
    async def test_list_members_owner_first(self, client: AsyncClient, override_db) -> None:
        """成员列表：owner 恒在首位（即使加入更晚），字段完整."""
        project = _project()
        owner_joined = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
        member_joined = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
        session = override_db([])
        members_result = MagicMock()
        members_result.all.return_value = [
            (_member(MEMBER_ID, member_joined), _user(MEMBER_ID, "member@x.com")),
            (_member(OWNER_ID, owner_joined), _user(OWNER_ID, "owner@x.com")),
        ]
        session.execute.side_effect = [
            _result(project),  # list_project_members 内查 project
            _result(project),  # _check_project_member 查 project
            members_result,  # JOIN 成员查询
        ]

        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/members", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert [m["user_id"] for m in items] == [str(OWNER_ID), str(MEMBER_ID)]
        assert items[0]["is_owner"] is True
        assert items[0]["email"] == "owner@x.com"
        assert items[0]["joined_at"] is not None
        assert items[1]["is_owner"] is False
        assert items[1]["display_name"] == f"用户{MEMBER_ID.hex[:4]}"

    @pytest.mark.asyncio
    async def test_list_members_forbidden_for_non_member(
        self, client: AsyncClient, override_db
    ) -> None:
        """非项目成员访问成员列表 → 403."""
        project = _project()
        override_db([project, project, None])
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/members", headers=_headers(OTHER_ID)
        )
        assert resp.status_code == 403


class TestRemoveMember:
    """DELETE /projects/{project_id}/members/{user_id}."""

    @pytest.mark.asyncio
    async def test_remove_succeeds_with_audit_and_commit(
        self, client: AsyncClient, override_db
    ) -> None:
        """owner 移除协作者：删除成员 + 审计 project.member_remove + 显式 commit."""
        project = _project()
        target = _member(MEMBER_ID, datetime(2026, 8, 16, 9, 0, tzinfo=UTC))
        session = override_db([project, project, target])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action, kwargs))

        with patch.object(projects_api.audit, "record", fake_record):
            resp = await client.delete(
                f"/api/v1/projects/{PROJECT_ID}/members/{MEMBER_ID}",
                headers=_headers(OWNER_ID),
            )
        assert resp.status_code == 200
        assert recorded == [
            (
                OWNER_ID,
                "project.member_remove",
                {"project_id": PROJECT_ID, "target_type": "member", "target_id": str(MEMBER_ID)},
            )
        ]
        session.delete.assert_awaited_once_with(target)
        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_remove_forbidden_for_non_owner(self, client: AsyncClient, override_db) -> None:
        """非 owner 移除成员 → 403."""
        override_db([_project(OTHER_ID)])  # owner 判定依赖查询即拦截
        resp = await client.delete(
            f"/api/v1/projects/{PROJECT_ID}/members/{MEMBER_ID}",
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_remove_owner_forbidden(self, client: AsyncClient, override_db) -> None:
        """移除项目所有者 → 4000."""
        project = _project()
        override_db([project, project])
        resp = await client.delete(
            f"/api/v1/projects/{PROJECT_ID}/members/{OWNER_ID}",
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000
        assert "所有者" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_remove_self_forbidden(self, client: AsyncClient, override_db) -> None:
        """移除自己 → 4000（owner 在成员表中，先被所有者保护拦截）."""
        project = _project()
        override_db([project, project])
        resp = await client.delete(
            f"/api/v1/projects/{PROJECT_ID}/members/{OWNER_ID}",
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000

    @pytest.mark.asyncio
    async def test_remove_nonexistent_member_404(self, client: AsyncClient, override_db) -> None:
        """目标不在成员表 → 404."""
        project = _project()
        override_db([project, project, None])
        resp = await client.delete(
            f"/api/v1/projects/{PROJECT_ID}/members/{MEMBER_ID}",
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 404
