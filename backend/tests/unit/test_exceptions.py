"""异常类单元测试."""

from app.core.exceptions import (
    BizError,
    ForbiddenError,
    LLMServiceError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def test_biz_error_attributes() -> None:
    """BizError 携带正确的 code/message/data."""
    err = BizError(code=4000, message="test error", data={"key": "value"})
    assert err.code == 4000
    assert err.message == "test error"
    assert err.data == {"key": "value"}


def test_not_found_error() -> None:
    """NotFoundError 默认 code=4004."""
    err = NotFoundError("项目")
    assert err.code == 4004
    assert "项目" in err.message


def test_forbidden_error() -> None:
    """ForbiddenError 默认 code=4003."""
    err = ForbiddenError()
    assert err.code == 4003


def test_unauthorized_error() -> None:
    """UnauthorizedError 默认 code=4001."""
    err = UnauthorizedError()
    assert err.code == 4001


def test_validation_error() -> None:
    """ValidationError 默认 code=4000."""
    err = ValidationError()
    assert err.code == 4000


def test_llm_service_error() -> None:
    """LLMServiceError 默认 code=5001."""
    err = LLMServiceError()
    assert err.code == 5001
