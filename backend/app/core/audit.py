"""审计日志统一封装 — 对齐 docs/agents/security.md §4.

关键操作留痕统一走 record()，禁止散落各处；
审计写入失败仅记 warning 日志，不阻断业务流程。
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# detail 中命中这些键的值一律不落库（大小写不敏感）
SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
}


def _sanitize(value: Any) -> Any:
    """递归剥离 detail 中的敏感字段."""
    if isinstance(value, dict):
        return {
            k: _sanitize(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.lower() in SENSITIVE_KEYS)
        }
    return value


async def record(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog | None:
    """写入一条审计记录（随当前事务提交）.

    action 命名规范：域.动作，如 auth.login / document.upload / workflow.start。
    失败时仅记 warning，返回 None，不抛异常。
    """
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            detail=_sanitize(detail),
        )
        db.add(log)
        return log
    except Exception:
        logger.warning("审计日志写入失败: action=%s user_id=%s", action, user_id, exc_info=True)
        return None
