"""健康检查与基础 API 测试."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """健康检查端点返回 200."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_biz_error_handler(client: AsyncClient) -> None:
    """404 路径不触发未处理异常."""
    response = await client.get("/nonexistent")
    assert response.status_code == 404
