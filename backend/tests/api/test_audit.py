"""api/audit.py 测试 — 三期 S3 审计日志查询（admin only，只读追加式）."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User

ADMIN_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _user(user_id: uuid.UUID, email: str, role: str = "member") -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="x",
        display_name="测试用户",
        role=role,
        created_at=datetime.now(UTC),
    )


def _log(**overrides) -> AuditLog:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": MEMBER_ID,
        "action": "kb.material_delete",
        "project_id": None,
        "target_type": "document",
        "target_id": "doc-1",
        "detail": {"from": "a", "to": "b"},
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return AuditLog(**defaults)


def _session(user: User | None, items: list = (), total: int = 0) -> AsyncMock:
    """execute 序列：鉴权载入用户 → count → items."""
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    count_result = MagicMock()
    count_result.scalar.return_value = total
    items_result = MagicMock()
    items_result.all.return_value = items
    session.execute.side_effect = [user_result, count_result, items_result]
    return session


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(ADMIN_ID))}"}


def _stmts(session: AsyncMock) -> str:
    return " ".join(str(c.args[0]) for c in session.execute.call_args_list)


class TestAuditLogsPermission:
    """GET /audit-logs 权限."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/audit-logs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient) -> None:
        """member 角色 → 403（仅 admin 可查审计）."""
        session = _session(_user(ADMIN_ID, "m@example.com", role="member"))
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get("/api/v1/audit-logs", headers=_admin_headers())
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestAuditLogsQuery:
    """GET /audit-logs 查询与过滤."""

    @pytest.mark.asyncio
    async def test_list_returns_items_with_user_name(self, client: AsyncClient) -> None:
        """返回契约：code=0 + items/total，LEFT JOIN users 返回 user_name."""
        session = _session(
            _user(ADMIN_ID, "a@example.com", role="admin"),
            items=[(_log(), "张三")],
            total=1,
        )
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get("/api/v1/audit-logs", headers=_admin_headers())
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 1
            item = data["items"][0]
            assert item["action"] == "kb.material_delete"
            assert item["user_name"] == "张三"
            assert item["detail"] == {"from": "a", "to": "b"}
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_filters_pushed_to_sql(self, client: AsyncClient) -> None:
        """action 前缀/user_id/project_id/target_type/时间范围 全部下推 SQL，倒序分页."""
        session = _session(_user(ADMIN_ID, "a@example.com", role="admin"))
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get(
                "/api/v1/audit-logs",
                params={
                    "action": "kb.",
                    "user_id": str(MEMBER_ID),
                    "project_id": str(PROJECT_ID),
                    "target_type": "document",
                    "start": "2026-01-01T00:00:00",
                    "end": "2026-12-31T23:59:59",
                    "page": 2,
                    "page_size": 5,
                },
                headers=_admin_headers(),
            )
            assert resp.status_code == 200
            stmts = _stmts(session)
            assert "LIKE" in stmts  # action 前缀匹配
            assert "user_id" in stmts
            assert "project_id" in stmts
            assert "target_type" in stmts
            assert "DESC" in stmts  # created_at 倒序
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_query_itself_recorded_as_audit(self, client: AsyncClient) -> None:
        """查询行为自身记审计 audit.query（detail 含过滤条件）."""
        session = _session(_user(ADMIN_ID, "a@example.com", role="admin"))
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get(
                "/api/v1/audit-logs", params={"action": "kb."}, headers=_admin_headers()
            )
            assert resp.status_code == 200
            added = [c.args[0] for c in session.add.call_args_list]
            logs = [a for a in added if isinstance(a, AuditLog)]
            assert any(log.action == "audit.query" for log in logs)
            query_log = next(log for log in logs if log.action == "audit.query")
            assert query_log.detail["action"] == "kb."
            session.commit.assert_awaited()
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_user_name_empty_when_join_miss(self, client: AsyncClient) -> None:
        """用户已删除（LEFT JOIN 未命中）→ user_name 空串."""
        session = _session(
            _user(ADMIN_ID, "a@example.com", role="admin"),
            items=[(_log(), None)],
            total=1,
        )
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get("/api/v1/audit-logs", headers=_admin_headers())
            assert resp.json()["data"]["items"][0]["user_name"] == ""
        finally:
            app.dependency_overrides.pop(get_db, None)
