"""项目管理 API 测试."""

import pytest
from httpx import AsyncClient


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
