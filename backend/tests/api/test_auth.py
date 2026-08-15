"""认证 API 测试."""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.main import app
from app.models.audit_log import AuditLog


@pytest.fixture
def mock_db() -> Generator[AsyncMock, None, None]:
    """覆盖 get_db 注入 mock 会话（refresh 端点依赖 db 写审计）."""
    session = AsyncMock()
    session.add = MagicMock()  # audit.record 同步调用 add，不能用 AsyncMock
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


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


class TestRefreshToken:
    """/auth/refresh — refresh token 换新 access token."""

    @pytest.mark.asyncio
    async def test_refresh_valid_issues_new_access(self, client: AsyncClient, mock_db) -> None:
        """有效 refresh token 签发新 access token（sub 一致，type=access）."""
        user_id = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": create_refresh_token(user_id)},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        payload = decode_token(data["access_token"])
        assert payload is not None
        assert payload["sub"] == user_id
        assert payload["type"] == "access"

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token_returns_401(
        self, client: AsyncClient, mock_db
    ) -> None:
        """伪造 token 返回 401 业务错误码."""
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "forged.token.value"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == 4001

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_returns_401(
        self, client: AsyncClient, mock_db
    ) -> None:
        """拿 access token 当 refresh 用被拒绝（type 校验）."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": create_access_token(str(uuid.uuid4()))},
        )
        assert response.status_code == 401
        assert response.json()["code"] == 4001

    @pytest.mark.asyncio
    async def test_refresh_records_audit(self, client: AsyncClient, mock_db) -> None:
        """签发成功后记录一条 auth.refresh 审计（对齐 auth.login 埋点惯例）."""
        user_id = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": create_refresh_token(user_id)},
        )
        assert response.status_code == 200

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args.args[0]
        assert isinstance(added, AuditLog)
        assert added.action == "auth.refresh"
        assert str(added.user_id) == user_id
        assert added.target_type == "user"
        assert added.target_id == user_id
