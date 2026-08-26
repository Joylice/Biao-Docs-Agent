"""项目管理 API 测试."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project, ProjectMember
from app.models.user import User


@pytest.mark.asyncio
async def test_list_projects_without_auth(client: AsyncClient) -> None:
    """未认证访问项目列表返回 401/403."""
    response = await client.get("/api/v1/projects")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_project_without_auth(client: AsyncClient) -> None:
    """未认证创建项目返回 401/403."""
    response = await client.post(
        "/api/v1/projects",
        json={"name": "测试项目"},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_project_without_auth(client: AsyncClient) -> None:
    """未认证获取项目详情返回 401/403."""
    response = await client.get("/api/v1/projects/550e8400-e29b-41d4-a716-446655440000")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_add_member_without_auth(client: AsyncClient) -> None:
    """未认证添加成员返回 401/403."""
    response = await client.post(
        "/api/v1/projects/550e8400-e29b-41d4-a716-446655440000/members",
        json={"email": "test@example.com"},
    )
    assert response.status_code in (401, 403)


class _FakeProjectSession:
    """创建项目的假会话：flush 补 id/status，refresh 补 created_at，记录 commit."""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, stmt):
        return MagicMock()

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if isinstance(obj, Project) and getattr(obj, "status", None) is None:
                obj.status = "active"

    async def refresh(self, obj) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_create_project_commits_before_response(client: AsyncClient) -> None:
    """BUG-1：创建项目显式提交（新建项目立即可查，不再短暂 404）."""
    session = _FakeProjectSession()
    app.dependency_overrides[get_db] = lambda: session
    try:
        owner_id = uuid.uuid4()
        response = await client.post(
            "/api/v1/projects",
            json={"name": "提交竞态项目", "tender_no": "T-COMMIT-1"},
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        assert session.committed is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def _user_row(user_id: uuid.UUID, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="x",
        display_name="用户",
        role="member",
        created_at=datetime.now(UTC),
    )


class TestCreateProjectWithMembers:
    """阶段7：建项目选成员（member_ids → project_members）."""

    def _session_with_users(self, users: list[User]) -> _FakeProjectSession:
        session = _FakeProjectSession()

        async def execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = users
            return result

        session.execute = execute
        return session

    @pytest.mark.asyncio
    async def test_create_with_member_ids_writes_memberships(self, client: AsyncClient) -> None:
        """member_ids 全部为已注册用户 → 写入 project_members（owner 额外一条）."""
        owner_id = uuid.uuid4()
        m1, m2 = uuid.uuid4(), uuid.uuid4()
        session = self._session_with_users([_user_row(m1, "m1@x.com"), _user_row(m2, "m2@x.com")])
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = await client.post(
                "/api/v1/projects",
                json={"name": "带成员项目", "member_ids": [str(m1), str(m2)]},
                headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            )
            assert response.status_code == 200
            member_ids = {m.user_id for m in session.added if isinstance(m, ProjectMember)}
            assert member_ids == {owner_id, m1, m2}
            assert session.committed is True
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_unknown_member_id_rejected(self, client: AsyncClient) -> None:
        """member_ids 含未注册用户 → BizError 4004，不创建成员."""
        owner_id = uuid.uuid4()
        session = self._session_with_users([])  # 查不到任何用户
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = await client.post(
                "/api/v1/projects",
                json={"name": "项目", "member_ids": [str(uuid.uuid4())]},
                headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            )
            assert response.status_code == 404
            assert response.json()["code"] == 4004
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_owner_in_member_ids_deduped(self, client: AsyncClient) -> None:
        """member_ids 含创建者自己 → 自动去重，不产生重复成员记录."""
        owner_id = uuid.uuid4()
        session = self._session_with_users([_user_row(owner_id, "owner@x.com")])
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = await client.post(
                "/api/v1/projects",
                json={"name": "项目", "member_ids": [str(owner_id)]},
                headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            )
            assert response.status_code == 200
            memberships = [m for m in session.added if isinstance(m, ProjectMember)]
            assert len(memberships) == 1
            assert memberships[0].user_id == owner_id
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestDeleteProject:
    """删除项目（2026-08-25 新增端点）：owner/admin 可删，级联清理关联数据."""

    def _session(self, project: Project, docs: list | None = None, user: User | None = None):
        """构造删除项目会话：execute 按 SQL 目标模型分发（与调用序无关）.

        调用序（delete_project）：
          - select(Project) → project（存在性 + owner 判定）
          - 非 owner 时 select(User) → user（RBAC 判定）
          - select(Document) → docs（MinIO storage_key 收集）
        """
        session = AsyncMock()
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        doc_result = MagicMock()
        doc_result.scalars.return_value.all.return_value = docs or []
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        async def fake_execute(stmt, *args, **kwargs):
            s = str(stmt)
            if "documents" in s:
                return doc_result
            if "users" in s:
                return user_result
            return project_result

        session.execute = fake_execute
        return session

    @pytest.mark.asyncio
    async def test_delete_by_owner_success(self, client: AsyncClient, monkeypatch) -> None:
        """owner 删除项目：200 + 项目被删除 + 审计 + MinIO 对象清理."""
        from app.services.project import project_service

        owner_id = uuid.uuid4()
        project = Project(id=uuid.uuid4(), name="待删项目", owner_id=owner_id)
        doc = MagicMock()
        doc.storage_key = "tender/abc.docx"

        session = self._session(project, docs=[doc])
        app.dependency_overrides[get_db] = lambda: session

        deleted_keys: list = []
        monkeypatch.setattr(project_service, "_delete_workflow_checkpoints", AsyncMock())
        monkeypatch.setattr(
            "app.services.document.storage_service.delete_file",
            lambda key: deleted_keys.append(key),
        )
        try:
            response = await client.delete(
                f"/api/v1/projects/{project.id}",
                headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            )
            assert response.status_code == 200
            session.delete.assert_awaited_once()
            assert deleted_keys == ["tender/abc.docx"], "项目关联文档 storage_key 应清理"
            session.commit.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_delete_forbidden_for_non_owner(self, client: AsyncClient, monkeypatch) -> None:
        """非 owner 且非 admin 删除 → 403."""
        from app.services.project import project_service

        owner_id = uuid.uuid4()
        other_id = uuid.uuid4()
        project = Project(id=uuid.uuid4(), name="项目", owner_id=owner_id)
        other_user = User(id=other_id, email="other@x.com", password_hash="x", role="member")

        session = self._session(project, docs=[], user=other_user)
        app.dependency_overrides[get_db] = lambda: session
        monkeypatch.setattr("app.core.rbac.has_permission", AsyncMock(return_value=False))
        monkeypatch.setattr(project_service, "_delete_workflow_checkpoints", AsyncMock())
        try:
            response = await client.delete(
                f"/api/v1/projects/{project.id}",
                headers={"Authorization": f"Bearer {create_access_token(str(other_id))}"},
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_delete_by_admin_success(self, client: AsyncClient, monkeypatch) -> None:
        """系统管理员（system:manage）删除任意项目 → 200."""
        from app.services.project import project_service

        owner_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        project = Project(id=uuid.uuid4(), name="项目", owner_id=owner_id)
        admin_user = User(id=admin_id, email="admin@x.com", password_hash="x", role="admin")

        session = self._session(project, docs=[], user=admin_user)
        app.dependency_overrides[get_db] = lambda: session
        monkeypatch.setattr("app.core.rbac.has_permission", AsyncMock(return_value=True))
        monkeypatch.setattr(project_service, "_delete_workflow_checkpoints", AsyncMock())
        try:
            response = await client.delete(
                f"/api/v1/projects/{project.id}",
                headers={"Authorization": f"Bearer {create_access_token(str(admin_id))}"},
            )
            assert response.status_code == 200
            session.delete.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client: AsyncClient) -> None:
        """项目不存在 → 404."""
        owner_id = uuid.uuid4()
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = await client.delete(
                f"/api/v1/projects/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_delete_without_auth(self, client: AsyncClient) -> None:
        """未认证删除项目 → 401/403."""
        response = await client.delete(f"/api/v1/projects/{uuid.uuid4()}")
        assert response.status_code in (401, 403)
