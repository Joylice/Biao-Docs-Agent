"""LLM 错误分类（P1-6 拆分自 llm_service.py）.

RETRYABLE 可重试（瞬时故障）/ FATAL 快速失败（确定性故障），
供 caller / llm_service 及重试策略统一引用。
"""

import asyncio
from enum import Enum


class LLMErrorCategory(Enum):
    """LLM 错误分类：RETRYABLE 可重试（瞬时故障）/ FATAL 快速失败（确定性故障）."""

    RETRYABLE = "retryable"
    FATAL = "fatal"


def classify_llm_error(e: BaseException) -> LLMErrorCategory:
    """按异常类型/状态码/报文关键词分类 LLM 错误.

    RETRYABLE：timeout / 连接错 / 429 / 5xx（瞬时故障，可安全重试）；
    FATAL：400/401/403 / 上下文超限(context_length) / 响应格式错（确定性故障）；
    未识别错误 → FATAL（fail-loud：不盲目重试，直接透出根因）。
    """
    if isinstance(e, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return LLMErrorCategory.RETRYABLE

    # 异常类名（覆盖 litellm Timeout/RateLimitError/APIConnectionError 等类型化异常）
    name = type(e).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "ratelimit", "serviceunavailable")):
        return LLMErrorCategory.RETRYABLE
    if any(
        k in name
        for k in ("auth", "permission", "forbidden", "badrequest", "invalidrequest", "json")
    ):
        return LLMErrorCategory.FATAL

    # HTTP 状态码属性（litellm/SDK 异常常见）
    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        if status == 429 or 500 <= status < 600:
            return LLMErrorCategory.RETRYABLE
        if 400 <= status < 500:
            return LLMErrorCategory.FATAL

    # 报文关键词兜底（错误信息形如 "Error code: 429 - ..."）
    text = str(e).lower()
    retryable_markers = (
        "timeout",
        "timed out",
        "connection",
        "connect",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "server error",
        "overloaded",
        "temporarily",
    )
    if any(m in text for m in retryable_markers):
        return LLMErrorCategory.RETRYABLE
    fatal_markers = (
        "400",
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "authentication",
        "invalid api key",
        "bad request",
        "invalid request",
        "context_length",
        "context length",
        "maximum context",
        "response_format",
        "not json",
    )
    if any(m in text for m in fatal_markers):
        return LLMErrorCategory.FATAL
    # 未识别 → FATAL（fail-loud：透出根因，不自动重试）
    return LLMErrorCategory.FATAL
