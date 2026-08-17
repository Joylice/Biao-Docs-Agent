"""用户管理 API 测试（三期 S1：角色细分 member/kb_admin/admin）.

覆盖：
- GET /users：admin 放行（列表字段/keyword 与 role 过滤 SQL/分页契约）、非 admin 403、401
- PUT /users/{id}/role：授权成功 + 审计、非法 role 422、禁止变更自身角色、
  最后一名 admin 保护、非 admin 403、目标用户不存在 404
- kb 删除权限回归：kb_admin 角色放行（不依赖邮箱白名单）
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.users as users_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import Document
from app.models.user import User

ADMIN_ID = uuid.uuid4()
KB_ADMIN_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _user(user_id: uuid.UUID, email: str, role: str = "member") -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="x",
        display_name="测试用户",
        role=role,
        created_at=datetime.now(UTC),  # 生产由 server_default 填充，测试显式构造
    )


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


class TestListUsers:
    """GET /users."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient, override_db) -> None:
        """member 角色访问用户列表 → 403（无白名单兜底场景）."""
        override_db([_user(MEMBER_ID, "member@x.com")])
        resp = await client.get("/api/v1/users", headers=_headers(MEMBER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_lists_users_with_role_field(
        self, client: AsyncClient, override_db
    ) -> None:
        """admin（role 判定，无白名单）放行：返回项含 role，不泄露密码哈希."""
        session = override_db([_user(ADMIN_ID, "admin@x.com", "admin"), []])
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [
            _user(MEMBER_ID, "member@x.com"),
        ]
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        session.execute.side_effect = [
            _result(_user(ADMIN_ID, "admin@x.com", "admin")),
            count_result,
            items_result,
        ]

        resp = await client.get("/api/v1/users", headers=_headers(ADMIN_ID))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        item = data["items"][0]
        assert item["role"] == "member"
        assert item["email"] == "member@x.com"
        assert "password_hash" not in item

    @pytest.mark.asyncio
    async def test_filters_applied_in_sql(self, client: AsyncClient, override_db) -> None:
        """keyword/role 过滤条件下推到 SQL."""
        session = override_db([_user(ADMIN_ID, "admin@x.com", "admin"), [], []])
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []
        session.execute.side_effect = [
            _result(_user(ADMIN_ID, "admin@x.com", "admin")),
            count_result,
            items_result,
        ]

        resp = await client.get(
            "/api/v1/users",
            params={"keyword": "zhang", "role": "kb_admin"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 200
        stmts = [str(c.args[0]) for c in session.execute.call_args_list[1:]]
        joined = " ".join(stmts).replace("\n", " ")
        assert "lower" in joined  # keyword ilike（大小写不敏感）
        assert "role" in joined

    @pytest.mark.asyncio
    async def test_invalid_role_filter_rejected(self, client: AsyncClient, override_db) -> None:
        """role 过滤值非法 → 422（枚举校验）."""
        override_db([_user(ADMIN_ID, "admin@x.com", "admin")])
        resp = await client.get(
            "/api/v1/users", params={"role": "superuser"}, headers=_headers(ADMIN_ID)
        )
        assert resp.status_code == 422


class TestUpdateUserRole:
    """PUT /users/{user_id}/role."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.put(f"/api/v1/users/{MEMBER_ID}/role", json={"role": "kb_admin"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_user(MEMBER_ID, "member@x.com")])
        resp = await client.put(
            f"/api/v1/users/{KB_ADMIN_ID}/role",
            json={"role": "member"},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, client: AsyncClient, override_db) -> None:
        override_db([_user(ADMIN_ID, "admin@x.com", "admin")])
        resp = await client.put(
            f"/api/v1/users/{MEMBER_ID}/role",
            json={"role": "superuser"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_grant_kb_admin_succeeds_with_audit(
        self, client: AsyncClient, override_db
    ) -> None:
        """授权 kb_admin：目标用户 role 更新 + 审计 user.role_change + commit."""
        target = _user(MEMBER_ID, "member@x.com")
        session = override_db([_user(ADMIN_ID, "admin@x.com", "admin"), target, 1])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action, kwargs))

        with patch.object(users_api.audit, "record", fake_record):
            resp = await client.put(
                f"/api/v1/users/{MEMBER_ID}/role",
                json={"role": "kb_admin"},
                headers=_headers(ADMIN_ID),
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["role"] == "kb_admin"
        assert target.role == "kb_admin"
        session.commit.assert_awaited()
        assert recorded and recorded[0][1] == "user.role_change"
        assert recorded[0][2]["target_id"] == str(MEMBER_ID)

    @pytest.mark.asyncio
    async def test_cannot_change_own_role(self, client: AsyncClient, override_db) -> None:
        """禁止变更自身角色（防止管理员误操作自我降级/提权）."""
        override_db([_user(ADMIN_ID, "admin@x.com", "admin")])
        resp = await client.put(
            f"/api/v1/users/{ADMIN_ID}/role",
            json={"role": "member"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000

    @pytest.mark.asyncio
    async def test_last_admin_protection(self, client: AsyncClient, override_db) -> None:
        """最后一名 admin 不可被降级（admin 计数 = 1 且目标为该 admin）."""
        target = _user(KB_ADMIN_ID, "last@x.com", "admin")
        override_db([_user(ADMIN_ID, "admin@x.com", "admin"), target, 1])
        resp = await client.put(
            f"/api/v1/users/{KB_ADMIN_ID}/role",
            json={"role": "member"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000

    @pytest.mark.asyncio
    async def test_demote_admin_allowed_when_others_exist(
        self, client: AsyncClient, override_db
    ) -> None:
        """存在其他 admin 时允许降级（admin 计数 = 2）."""
        target = _user(KB_ADMIN_ID, "other@x.com", "admin")
        session = override_db([_user(ADMIN_ID, "admin@x.com", "admin"), target, 2])
        resp = await client.put(
            f"/api/v1/users/{KB_ADMIN_ID}/role",
            json={"role": "member"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 200
        assert target.role == "member"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_target_not_found(self, client: AsyncClient, override_db) -> None:
        """目标用户不存在 → BizError 4004（HTTP 404）."""
        override_db([_user(ADMIN_ID, "admin@x.com", "admin"), None])
        resp = await client.put(
            f"/api/v1/users/{MEMBER_ID}/role",
            json={"role": "kb_admin"},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004


class TestKbDeleteRoleBased:
    """DELETE /kb/materials 权限回归（三期：role 判定 + 白名单兼容）."""

    def _global_doc(self) -> Document:
        return Document(
            id=DOC_ID,
            project_id=None,
            doc_type="kb_material",
            title="手册.pdf",
            storage_key=f"global/{DOC_ID}/手册.pdf",
            status="indexed",
            created_at=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_kb_admin_role_can_delete_without_whitelist(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """kb_admin 角色直接放行（无需邮箱白名单）."""
        session = override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin"), self._global_doc()])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        monkeypatch.setattr("app.api.kb.storage_service.delete_file", lambda *a, **k: None)

        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=_headers(KB_ADMIN_ID))
        assert resp.status_code == 200
        session.delete.assert_awaited()

    @pytest.mark.asyncio
    async def test_member_still_forbidden(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """member 角色且不在白名单 → 403."""
        override_db([_user(MEMBER_ID, "member@x.com")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=_headers(MEMBER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_whitelist_compat_admin_role_not_required(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """白名单兼容：role=member 但邮箱在 BID_ADMIN_USER_IDS → 视为管理员放行."""
        session = override_db([_user(MEMBER_ID, "legacy@x.com"), self._global_doc()])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "legacy@x.com")
        monkeypatch.setattr("app.api.kb.storage_service.delete_file", lambda *a, **k: None)

        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        session.delete.assert_awaited()


class TestMeIncludesRole:
    """GET /auth/me 返回 role（前端按角色渲染入口）."""

    @pytest.mark.asyncio
    async def test_me_returns_role(self, client: AsyncClient, override_db) -> None:
        override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin")])
        resp = await client.get("/api/v1/auth/me", headers=_headers(KB_ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["role"] == "kb_admin"
