"""认证 API 测试."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient) -> None:
    """注册成功."""
    # 注意：此测试需要数据库连接，在没有 DB 时会跳过
    # 实际 CI 环境中会有 PostgreSQL 服务
    pytest.skip("需要真实数据库连接，在集成测试中覆盖")


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    """密码错误返回业务错误."""
    pytest.skip("需要真实数据库连接")


@pytest.mark.asyncio
async def test_me_without_token(client: AsyncClient) -> None:
    """未携带 token 访问 /me 返回 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient) -> None:
    """无效 token 返回 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )
    assert response.status_code == 401
