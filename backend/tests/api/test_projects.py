"""项目管理 API 测试."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project


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
