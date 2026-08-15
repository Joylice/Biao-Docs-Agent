"""认证安全模块单元测试."""

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    """密码哈希与验证."""
    password = "secure_password_123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong_password", hashed)


def test_create_and_decode_access_token() -> None:
    """access token 创建与解码."""
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token() -> None:
    """refresh token 创建与解码."""
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    token = create_refresh_token(user_id)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


def test_decode_invalid_token() -> None:
    """无效 token 返回 None."""
    result = decode_token("invalid.token.here")
    assert result is None


def test_decode_empty_token() -> None:
    """空 token 返回 None."""
    result = decode_token("")
    assert result is None
