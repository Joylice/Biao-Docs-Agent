"""RBAC 权限点配置 API 测试（阶段 A：角色权限配置页后端）.

覆盖：
- GET /rbac/permissions：admin 放行（权限点目录含 code/name/category）；member 403
- GET /rbac/roles/{role}/permissions：admin 放行返回映射；非法角色 422；member 403
- PUT /rbac/roles/{role}/permissions：全量覆盖 + 缓存失效 + 审计；
  admin 角色禁止移除 system:manage（防自我锁死）；非法权限码 422；
  project:member_manage 为数据属性不可授予 422
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.users as users_api
import app.core.rbac as rbac
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User

# 与 tests/api/conftest.py 的 _rbac_seed 桩一致：role_permissions 不查库，
# 读路径断言一律对齐种子映射
SEED = {
    "member": {"kb:read", "kb:upload", "settings:read"},
    "kb_admin": {"kb:read", "kb:upload", "settings:read", "kb:manage"},
    "admin": {"system:manage", "kb:manage", "kb:read", "kb:upload", "settings:read"},
}

ADMIN_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()


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
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def override_db() -> Generator:
    """按预设 result 序列覆盖 get_db，用例结束清理并失效 RBAC 缓存."""
    rbac.invalidate_rbac_cache()

    def _override(result_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = list(result_sequence)
        # add/add_all 在 AsyncSession 上是同步方法，桩为同步 MagicMock
        session.add = MagicMock()
        session.add_all = MagicMock()
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)
    rbac.invalidate_rbac_cache()


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


class TestListPermissions:
    """GET /rbac/permissions."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/rbac/permissions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(MEMBER_ID, "m@x.com"))])
        resp = await client.get("/api/v1/rbac/permissions", headers=_headers(MEMBER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_lists_permission_catalog(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.get("/api/v1/rbac/permissions", headers=_headers(ADMIN_ID))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        codes = {i["code"] for i in items}
        assert "system:manage" in codes and "kb:read" in codes
        sys_item = next(i for i in items if i["code"] == "system:manage")
        assert sys_item["category"] == "system"
        assert sys_item["name"]  # 非空描述


class TestGetRolePermissions:
    """GET /rbac/roles/{role}/permissions."""

    @pytest.mark.asyncio
    async def test_admin_reads_member_mapping(self, client: AsyncClient, override_db) -> None:
        """读路径走种子桩（不消耗额外 execute），返回 member 种子权限点."""
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.get("/api/v1/rbac/roles/member/permissions", headers=_headers(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["role"] == "member"
        assert set(resp.json()["data"]["codes"]) == SEED["member"]

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.get(
            "/api/v1/rbac/roles/superuser/permissions", headers=_headers(ADMIN_ID)
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(MEMBER_ID, "m@x.com"))])
        resp = await client.get(
            "/api/v1/rbac/roles/member/permissions", headers=_headers(MEMBER_ID)
        )
        assert resp.status_code == 403


class TestPutRolePermissions:
    """PUT /rbac/roles/{role}/permissions."""

    @pytest.mark.asyncio
    async def test_full_replace_with_audit_and_cache_invalidation(
        self, client: AsyncClient, override_db
    ) -> None:
        """全量覆盖：先删除既有映射再插入新集合 + 审计 rbac.update + 缓存失效."""
        # execute 序列：1) require_permission 加载用户 2) set_role_permissions 的 delete
        session = override_db([_result(_user(ADMIN_ID, "a@x.com", "admin")), _result(None)])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action, kwargs))

        rbac.invalidate_rbac_cache()
        with patch.object(users_api.audit, "record", fake_record):
            resp = await client.put(
                "/api/v1/rbac/roles/member/permissions",
                json={"codes": ["kb:read", "settings:read"]},
                headers=_headers(ADMIN_ID),
            )
        assert resp.status_code == 200
        assert set(resp.json()["data"]["codes"]) == {"kb:read", "settings:read"}
        session.commit.assert_awaited()
        # execute：1 用户加载 + 1 delete；插入走 add_all（同步）
        assert session.execute.await_count == 2
        assert session.add_all.call_count == 1
        added = session.add_all.call_args.args[0]
        assert {rp.permission_code for rp in added} == {"kb:read", "settings:read"}
        assert recorded and recorded[0][1] == "rbac.update"
        assert recorded[0][2]["detail"]["role"] == "member"
        # 缓存失效：写入后旧映射缓存被清空
        assert rbac._role_permission_cache is None

    @pytest.mark.asyncio
    async def test_admin_cannot_lose_system_manage(self, client: AsyncClient, override_db) -> None:
        """防自我锁死：admin 角色映射必须包含 system:manage."""
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.put(
            "/api/v1/rbac/roles/admin/permissions",
            json={"codes": ["kb:read"]},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4000

    @pytest.mark.asyncio
    async def test_unknown_permission_code_rejected(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.put(
            "/api/v1/rbac/roles/member/permissions",
            json={"codes": ["kb:read", "nonexistent:perm"]},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_project_member_manage_not_grantable(
        self, client: AsyncClient, override_db
    ) -> None:
        """project:member_manage 为 owner 数据属性，不可授予角色."""
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.put(
            "/api/v1/rbac/roles/member/permissions",
            json={"codes": ["kb:read", "project:member_manage"]},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.put(
            "/api/v1/rbac/roles/superuser/permissions",
            json={"codes": ["kb:read"]},
            headers=_headers(ADMIN_ID),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_member_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_user(MEMBER_ID, "m@x.com"))])
        resp = await client.put(
            "/api/v1/rbac/roles/member/permissions",
            json={"codes": ["system:manage"]},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 403


class TestMeIncludesPermissions:
    """GET /auth/me 返回权限点列表（前端菜单权限点驱动）."""

    @pytest.mark.asyncio
    async def test_me_returns_permissions_for_role(self, client: AsyncClient, override_db) -> None:
        """kb_admin 角色按种子映射返回权限点（无白名单）."""
        override_db([_result(_user(uuid.uuid4(), "kb@x.com", "kb_admin"))])
        resp = await client.get("/api/v1/auth/me", headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert set(resp.json()["data"]["permissions"]) == SEED["kb_admin"]

    @pytest.mark.asyncio
    async def test_me_admin_has_all_functional_permissions(
        self, client: AsyncClient, override_db
    ) -> None:
        """admin 恒含全部功能权限点（project:member_manage 除外）."""
        override_db([_result(_user(ADMIN_ID, "a@x.com", "admin"))])
        resp = await client.get("/api/v1/auth/me", headers=_headers(ADMIN_ID))
        assert resp.status_code == 200
        perms = set(resp.json()["data"]["permissions"])
        assert "system:manage" in perms
        assert "project:member_manage" not in perms
