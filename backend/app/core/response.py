"""统一响应格式."""

from typing import Any

from fastapi.responses import JSONResponse


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应."""
    return {"code": 0, "message": message, "data": data}


def paginated(items: list[Any], total: int) -> dict[str, Any]:
    """分页响应."""
    return {"code": 0, "message": "ok", "data": {"items": items, "total": total}}


def error_response(code: int, message: str, status_code: int = 400) -> JSONResponse:
    """错误响应."""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "data": None},
    )
