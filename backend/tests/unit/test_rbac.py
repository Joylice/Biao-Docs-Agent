"""RBAC 权限体系测试 — 权限点目录/角色映射/缓存/白名单兼容/require_permission（无需真实 DB）.

说明：数据层经 mock 会话注入（与 test_audit.py 风格一致，不依赖真实 PostgreSQL）；
缓存为模块级，用例间以 autouse fixture 清理。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import rbac
from app.core.exceptions import ForbiddenError
from app.models.rbac import Permission, Role, RolePermission
from app.models.user import User

ALL_FUNCTIONAL_PERMISSIONS = {"system:manage", "kb:manage", "kb:read", "kb:upload", "settings:read"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    """每个用例前后清空模块级缓存，避免用例间污染."""
    rbac.invalidate_rbac_cache()
    yield
    rbac.invalidate_rbac_cache()


def _user(email: str = "u@x.com", role: str = "member") -> User:
    return User(id=uuid.uuid4(), email=email, password_hash="x", display_name="测试", role=role)


def _session_with_rp_rows(rows: list) -> AsyncMock:
    """mock 会话：execute 返回 RolePermission 行列表."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result
    return session


def _rp(role_code: str, permission_code: str) -> RolePermission:
    return RolePermission(role_code=role_code, permission_code=permission_code)


class TestModelMetadata:
    """三表元数据检查."""

    def test_tables_exist(self) -> None:
        assert Role.__tablename__ == "roles"
        assert Permission.__tablename__ == "permissions"
        assert RolePermission.__tablename__ == "role_permissions"

    def test_permission_columns(self) -> None:
        cols = Permission.__table__.columns
        for name in ("code", "name", "category"):
            assert name in cols
        assert Permission.__table__.c.code.nullable is False

    def test_role_permission_composite_pk(self) -> None:
        assert list(RolePermission.__table__.primary_key.columns.keys()) == [
            "role_code",
            "permission_code",
        ]


class TestPermissionCatalog:
    """权限点目录与分类一致性."""

    def test_has_six_permissions(self) -> None:
        assert set(rbac.PERMISSIONS) == ALL_FUNCTIONAL_PERMISSIONS | {"project:member_manage"}

    def test_categories_align_with_permissions(self) -> None:
        assert set(rbac.PERMISSION_CATEGORIES) == set(rbac.PERMISSIONS)


class TestRolePermissionMapping:
    """角色 → 权限点解析（DB 行 → 集合）."""

    async def test_member_mapping(self) -> None:
        session = _session_with_rp_rows(
            [_rp("member", "kb:read"), _rp("member", "kb:upload"), _rp("member", "settings:read")]
        )
        perms = await rbac.role_permissions(session, "member")
        assert perms == frozenset({"kb:read", "kb:upload", "settings:read"})
        assert "kb:manage" not in perms

    async def test_admin_mapping_contains_all_functional(self) -> None:
        session = _session_with_rp_rows(
            [_rp("admin", c) for c in sorted(ALL_FUNCTIONAL_PERMISSIONS)]
        )
        assert await rbac.role_permissions(session, "admin") == frozenset(
            ALL_FUNCTIONAL_PERMISSIONS
        )

    async def test_unknown_role_empty(self) -> None:
        session = _session_with_rp_rows([])
        assert await rbac.role_permissions(session, "nobody") == frozenset()


class TestCache:
    """缓存：命中不重复查询；失效后重载."""

    async def test_second_call_uses_cache(self) -> None:
        session = _session_with_rp_rows([_rp("member", "kb:read")])
        await rbac.role_permissions(session, "member")
        await rbac.role_permissions(session, "member")
        assert session.execute.await_count == 1

    async def test_invalidate_reloads(self) -> None:
        session = _session_with_rp_rows([_rp("member", "kb:read")])
        await rbac.role_permissions(session, "member")
        rbac.invalidate_rbac_cache()
        await rbac.role_permissions(session, "member")
        assert session.execute.await_count == 2


class TestHasPermission:
    """用户权限判定：白名单 / admin 恒全量 / 角色映射."""

    async def test_whitelist_email_grants_system_manage(self, monkeypatch) -> None:
        monkeypatch.setattr("app.core.rbac.settings.admin_user_ids", "boss@x.com")
        user = _user(email="boss@x.com", role="member")
        session = _session_with_rp_rows([])
        assert await rbac.has_permission(session, user, "system:manage") is True

    async def test_admin_always_has_functional_permissions(self) -> None:
        user = _user(role="admin")
        session = _session_with_rp_rows([])  # 映射缺失时 admin 仍恒有
        assert await rbac.has_permission(session, user, "kb:manage") is True

    async def test_kb_admin_has_kb_manage_not_system_manage(self) -> None:
        user = _user(role="kb_admin")
        session = _session_with_rp_rows(
            [_rp("kb_admin", "kb:read"), _rp("kb_admin", "kb:upload"), _rp("kb_admin", "kb:manage")]
        )
        assert await rbac.has_permission(session, user, "kb:manage") is True
        assert await rbac.has_permission(session, user, "system:manage") is False

    async def test_member_without_permission_denied(self) -> None:
        user = _user(role="member")
        session = _session_with_rp_rows([_rp("member", "kb:read")])
        assert await rbac.has_permission(session, user, "system:manage") is False


class TestRequirePermission:
    """require_permission 依赖工厂：直接调用 _check 验证授权与拒绝."""

    def _session_with_user(self, user: User | None) -> AsyncMock:
        """mock 会话：execute 返回同步 MagicMock（User 查询 + 空映射兜底）."""
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result
        return session

    async def test_granted_returns_user_id(self) -> None:
        user = _user(role="admin")
        check = rbac.require_permission("system:manage")
        assert await check(user_id=user.id, db=self._session_with_user(user)) == user.id

    async def test_denied_raises_forbidden(self) -> None:
        user = _user(role="member")
        check = rbac.require_permission("system:manage")
        with pytest.raises(ForbiddenError):
            await check(user_id=user.id, db=self._session_with_user(user))

    async def test_unknown_user_denied(self) -> None:
        check = rbac.require_permission("system:manage")
        with pytest.raises(ForbiddenError):
            await check(user_id=uuid.uuid4(), db=self._session_with_user(None))
