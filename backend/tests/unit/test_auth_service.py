"""auth_service 单元测试 — 注册/登录/refresh/me 的 DB 与业务逻辑（批次 1b 下沉）.

安全关键行为逐条等价验证：
- 注册邮箱查重 4000；建档只 flush 不 commit
- 登录标识缺失 4001；用户不存在/密码错误 4001（同一错误码不泄露细节）
- refresh token 伪造/拿 access 顶替 → 4001；有效 refresh → 返回 user_id
- token 签发：access/refresh 类型与 sub 正确
- /me 用户不存在 → 4004
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.services import auth_service

EMAIL = "commit@example.com"
PASSWORD = "Pass#12345"


def _session(scalar: object) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    session.execute.return_value = result
    return session


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        display_name="提交竞态",
    )


class TestRegisterUser:
    async def test_duplicate_email_raises_4000(self) -> None:
        session = _session(_user())
        with pytest.raises(BizError) as exc:
            await auth_service.register_user(session, EMAIL, PASSWORD, "显示名")
        assert exc.value.code == 4000
        assert exc.value.message == "该邮箱已注册"

    async def test_register_adds_user_flush_no_commit(self) -> None:
        """邮箱未注册：建档（密码哈希）+ flush/refresh，不 commit."""
        session = _session(None)
        user = await auth_service.register_user(session, EMAIL, PASSWORD, "显示名")
        assert user.email == EMAIL
        assert user.display_name == "显示名"
        assert verify_password(PASSWORD, user.password_hash)
        session.add.assert_called_once()
        assert session.add.call_args.args[0] is user
        session.flush.assert_awaited()
        session.refresh.assert_awaited()
        session.commit.assert_not_awaited()


class TestAuthenticateUser:
    async def test_missing_identifier_raises_4001(self) -> None:
        session = _session(None)
        with pytest.raises(BizError) as exc:
            await auth_service.authenticate_user(session, None, None, PASSWORD)
        assert exc.value.code == 4001
        assert exc.value.message == "请输入用户名或邮箱"

    async def test_user_not_found_raises_4001(self) -> None:
        session = _session(None)
        with pytest.raises(BizError) as exc:
            await auth_service.authenticate_user(session, None, EMAIL, PASSWORD)
        assert exc.value.code == 4001
        assert exc.value.message == "用户名或密码错误"

    async def test_wrong_password_raises_4001(self) -> None:
        session = _session(_user())
        with pytest.raises(BizError) as exc:
            await auth_service.authenticate_user(session, EMAIL, None, "Wrong#12345")
        assert exc.value.code == 4001
        assert exc.value.message == "用户名或密码错误"

    async def test_success_returns_user(self) -> None:
        user = _user()
        session = _session(user)
        result = await auth_service.authenticate_user(session, EMAIL, None, PASSWORD)
        assert result is user
        session.commit.assert_not_awaited()


class TestVerifyRefreshToken:
    def test_forged_token_raises_4001(self) -> None:
        with pytest.raises(BizError) as exc:
            auth_service.verify_refresh_token("forged.token.value")
        assert exc.value.code == 4001
        assert exc.value.message == "refresh token 无效或已过期"

    def test_access_token_rejected_4001(self) -> None:
        with pytest.raises(BizError) as exc:
            auth_service.verify_refresh_token(create_access_token(str(uuid.uuid4())))
        assert exc.value.code == 4001

    def test_valid_refresh_returns_user_id(self) -> None:
        user_id = uuid.uuid4()
        result = auth_service.verify_refresh_token(create_refresh_token(str(user_id)))
        assert result == user_id


class TestIssueTokenPair:
    def test_tokens_decodable_with_correct_types(self) -> None:
        user_id = str(uuid.uuid4())
        access_token, refresh_token = auth_service.issue_token_pair(user_id)
        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)
        assert access_payload is not None
        assert access_payload["sub"] == user_id
        assert access_payload["type"] == "access"
        assert refresh_payload is not None
        assert refresh_payload["sub"] == user_id
        assert refresh_payload["type"] == "refresh"


class TestGetUserById:
    async def test_missing_user_raises_4004(self) -> None:
        session = _session(None)
        with pytest.raises(BizError) as exc:
            await auth_service.get_user_by_id(session, uuid.uuid4())
        assert exc.value.code == 4004
        assert exc.value.message == "用户不存在"

    async def test_returns_user(self) -> None:
        user = _user()
        session = _session(user)
        result = await auth_service.get_user_by_id(session, user.id)
        assert result is user
