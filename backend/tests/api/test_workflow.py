"""工作流 API 测试."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project


@pytest.mark.asyncio
async def test_start_workflow_no_auth(client: AsyncClient) -> None:
    """未认证启动工作流返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/start"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_workflow_status_no_auth(client: AsyncClient) -> None:
    """未认证获取工作流状态返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/status"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_score_points_no_auth(client: AsyncClient) -> None:
    """未认证确认评分点返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-score-points"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_outline_no_auth(client: AsyncClient) -> None:
    """未认证确认大纲返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-outline"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_review_no_auth(client: AsyncClient) -> None:
    """未认证确认审阅返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-review"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_no_auth(client: AsyncClient) -> None:
    """未认证导出返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/export"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_start_workflow_commits_audit(client: AsyncClient, monkeypatch) -> None:
    """BUG-1：启动工作流的审计写入在响应前显式 commit."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()  # audit.record 同步调用 add
    app.dependency_overrides[get_db] = lambda: session

    async def fake_status(_pid) -> dict:
        return {"phase": "init", "progress": 0.0}

    monkeypatch.setattr(workflow_runtime, "start_workflow_in_background", lambda pid, uid: None)
    monkeypatch.setattr(workflow_runtime, "get_status_dict", fake_status)

    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/start",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        session.commit.assert_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)
