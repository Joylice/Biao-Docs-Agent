"""业务异常定义."""

from typing import Any


class BizError(Exception):
    """业务异常 — api 层统一捕获转 JSON.

    错误码约定：
    - 4xxx: 业务错误（参数/权限/资源不存在等）
    - 5xxx: 系统错误（内部异常/第三方调用失败等）
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


# ── 常用业务异常快捷构造 ──


class NotFoundError(BizError):
    """资源不存在."""

    def __init__(self, resource: str = "资源") -> None:
        super().__init__(code=4004, message=f"{resource}不存在")


class ForbiddenError(BizError):
    """权限不足."""

    def __init__(self, message: str = "无权访问") -> None:
        super().__init__(code=4003, message=message)


class UnauthorizedError(BizError):
    """未认证."""

    def __init__(self, message: str = "请先登录") -> None:
        super().__init__(code=4001, message=message)


class ValidationError(BizError):
    """参数校验失败."""

    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__(code=4000, message=message)


class LLMServiceError(BizError):
    """LLM 调用失败."""

    def __init__(self, message: str = "LLM 服务调用失败") -> None:
        super().__init__(code=5001, message=message)
