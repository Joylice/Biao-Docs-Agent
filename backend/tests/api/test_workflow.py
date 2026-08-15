"""工作流 API 测试."""

import pytest
from httpx import AsyncClient


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
