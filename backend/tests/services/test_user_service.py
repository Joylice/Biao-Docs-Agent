"""用户服务单测 — 用户 CRUD / 角色变更 / 密码重置（三期 S1 + 阶段4）.

覆盖 api 层下沉的 DB 语义：keyword/role 过滤、邮箱查重、最后一名 admin 保护、
自身角色变更拦截、名下项目保护、密码哈希（app.core.security）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.core.security import verify_password
from app.models.user import User
from app.services import user_service

ADMIN_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
KB_ADMIN_ID = uuid.uuid4()


def _user(user_id: uuid.UUID, email: str, role: str = "member") -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="x",
        display_name="测试用户",
        role=role,
        created_at=datetime.now(UTC),
    )


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _count_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def _users_result(users: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = users
    return result


class TestListUsers:
    @pytest.mark.asyncio
    async def test_filters_pushed_to_sql_count_then_items(self) -> None:
        """keyword ilike + role 过滤下推；先 count 后分页 items."""
        db = AsyncMock()
        db.execute.side_effect = [_count_result(1), _users_result([_user(MEMBER_ID, "m@x.com")])]
        users, total = await user_service.list_users(
            db, keyword="zhang", role="kb_admin", page=2, page_size=5
        )
        assert total == 1
        assert len(users) == 1
        stmts = " ".join(str(c.args[0]) for c in db.execute.await_args_list)
        assert "lower" in stmts  # keyword ilike（大小写不敏感）
        assert "role" in stmts
        assert "DESC" in stmts  # created_at 倒序


class TestListUserOptions:
    @pytest.mark.asyncio
    async def test_minimal_fields(self) -> None:
        """下拉项仅 id/email/display_name（注册正序）."""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_users_result([_user(MEMBER_ID, "m@x.com"), _user(KB_ADMIN_ID, "k@x.com")])
        )
        items = await user_service.list_user_options(db)
        assert items == [
            {"id": str(MEMBER_ID), "email": "m@x.com", "display_name": "测试用户"},
            {"id": str(KB_ADMIN_ID), "email": "k@x.com", "display_name": "测试用户"},
        ]


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_user(MEMBER_ID, "new@x.com")))
        with pytest.raises(BizError) as ei:
            await user_service.create_user(db, "new@x.com", "secret123", "新用户", "member")
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_creates_with_hashed_password(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        db.add = MagicMock()
        created = await user_service.create_user(db, "new@x.com", "secret123", "新用户", "member")
        db.add.assert_called_once()
        assert created.email == "new@x.com"
        assert created.role == "member"
        assert created.id is not None  # 显式生成：审计/响应立即可用
        assert verify_password("secret123", created.password_hash)


class TestUpdateRole:
    @pytest.mark.asyncio
    async def test_cannot_change_own_role_without_db(self) -> None:
        """自身角色拦截先于任何 DB 查询."""
        db = AsyncMock()
        with pytest.raises(BizError) as ei:
            await user_service.update_role(db, ADMIN_ID, "member", operator_id=ADMIN_ID)
        assert ei.value.code == 4000
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_target_not_found(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(BizError) as ei:
            await user_service.update_role(db, MEMBER_ID, "kb_admin", operator_id=ADMIN_ID)
        assert ei.value.code == 4004

    @pytest.mark.asyncio
    async def test_last_admin_protection(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_result(_user(KB_ADMIN_ID, "last@x.com", "admin")), _count_result(1)]
        )
        with pytest.raises(BizError) as ei:
            await user_service.update_role(db, KB_ADMIN_ID, "member", operator_id=ADMIN_ID)
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_updates_role_and_returns_old(self) -> None:
        target = _user(MEMBER_ID, "m@x.com")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(target))
        user, old_role = await user_service.update_role(
            db, MEMBER_ID, "kb_admin", operator_id=ADMIN_ID
        )
        assert user is target
        assert target.role == "kb_admin"
        assert old_role == "member"


class TestUpdateUser:
    @pytest.mark.asyncio
    async def test_updates_display_name_with_changes(self) -> None:
        target = _user(MEMBER_ID, "m@x.com")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(target))
        user, changes = await user_service.update_user(
            db, MEMBER_ID, display_name="新名字", role=None, operator_id=ADMIN_ID
        )
        assert user.display_name == "新名字"
        assert changes == {"display_name": {"from": "测试用户", "to": "新名字"}}

    @pytest.mark.asyncio
    async def test_cannot_change_own_role_via_edit(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_user(ADMIN_ID, "a@x.com", "admin")))
        with pytest.raises(BizError) as ei:
            await user_service.update_user(
                db, ADMIN_ID, display_name=None, role="member", operator_id=ADMIN_ID
            )
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_last_admin_protection(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_result(_user(KB_ADMIN_ID, "last@x.com", "admin")), _count_result(1)]
        )
        with pytest.raises(BizError) as ei:
            await user_service.update_user(
                db, KB_ADMIN_ID, display_name=None, role="member", operator_id=ADMIN_ID
            )
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_target_not_found(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(BizError) as ei:
            await user_service.update_user(
                db, MEMBER_ID, display_name="x", role=None, operator_id=ADMIN_ID
            )
        assert ei.value.code == 4004


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_resets_hash(self) -> None:
        target = _user(MEMBER_ID, "m@x.com")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(target))
        user = await user_service.reset_password(db, MEMBER_ID, "newpass123")
        assert user is target
        assert verify_password("newpass123", target.password_hash)

    @pytest.mark.asyncio
    async def test_target_not_found(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(BizError) as ei:
            await user_service.reset_password(db, MEMBER_ID, "newpass123")
        assert ei.value.code == 4004


class TestDeleteUser:
    @pytest.mark.asyncio
    async def test_cannot_delete_self_without_db(self) -> None:
        db = AsyncMock()
        with pytest.raises(BizError) as ei:
            await user_service.delete_user(db, ADMIN_ID, operator_id=ADMIN_ID)
        assert ei.value.code == 4000
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owner_projects_blocked(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result(_user(MEMBER_ID, "m@x.com")), _count_result(2)])
        with pytest.raises(BizError) as ei:
            await user_service.delete_user(db, MEMBER_ID, operator_id=ADMIN_ID)
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_last_admin_protection(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result(_user(KB_ADMIN_ID, "o@x.com", "admin")),
                _count_result(0),
                _count_result(1),
            ]
        )
        with pytest.raises(BizError) as ei:
            await user_service.delete_user(db, KB_ADMIN_ID, operator_id=ADMIN_ID)
        assert ei.value.code == 4000

    @pytest.mark.asyncio
    async def test_deletes_member(self) -> None:
        target = _user(MEMBER_ID, "m@x.com")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result(target), _count_result(0)])
        deleted = await user_service.delete_user(db, MEMBER_ID, operator_id=ADMIN_ID)
        assert deleted is target
        db.delete.assert_awaited_once_with(target)
