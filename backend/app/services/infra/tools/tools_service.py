"""外部工具 CRUD 服务 — 加密入库 / 三态密钥 / 乐观锁 / 绑定管理.

参照 providers.py 的 CRUD 模式：
- list_tools：返回脱敏列表（security.mask_secret）；
- create_tool：密钥加密入库（crypto.encrypt）；
- update_tool：三态密钥（None=保持/""=清除/非空=更新+拒收****）+ 乐观锁
  WHERE version=expected，冲突返回 ConflictError(409)；
- delete_tool：删除工具（级联删除绑定）；
- test_tool：调 call_external_tool 传 "test" 查询；
- bind_stage：白名单校验→不在白名单 422；
- unbind_stage：删除绑定；
- list_bindings：按 stage_key 列出绑定；
- invalidate_tools_cache：调 registry.invalidate()。
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.external_tool import ExternalTool, StageToolBinding
from app.services.infra.settings.security import (
    _decrypt_or_empty,
    _reject_masked_key,
    _validate_api_base,
    mask_secret,
)
from app.services.infra.tools.http_tool_client import call_external_tool
from app.services.infra.tools.registry import STAGE_TOOL_WHITELIST, invalidate

logger = logging.getLogger(__name__)


def _tool_to_view(tool: ExternalTool, bound_stages: list[str] | None = None) -> dict[str, Any]:
    """工具 ORM → 前端视图（密钥脱敏；含已绑定 stage_key 列表）."""
    plain_key = _decrypt_or_empty(tool.api_key_enc)
    return {
        "id": str(tool.id),
        "name": tool.name,
        "preset": tool.preset,
        "toolType": tool.tool_type,
        "apiKeyMasked": mask_secret(plain_key),
        "configured": bool(plain_key),
        "baseUrl": tool.base_url or "",
        "timeoutMs": tool.timeout_ms,
        "maxQueryChars": tool.max_query_chars,
        "enabled": tool.enabled,
        "version": tool.version,
        "boundStages": list(bound_stages or []),
    }


async def _load_bound_stage_map(
    db: AsyncSession, tool_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """一次性查出 tool_id → 已绑定 stage_key 列表（供 list_tools 批量附加，避免 N+1）."""
    if not tool_ids:
        return {}
    result = await db.execute(
        select(StageToolBinding.tool_id, StageToolBinding.stage_key).where(
            StageToolBinding.tool_id.in_(tool_ids)
        )
    )
    mapping: dict[uuid.UUID, list[str]] = {}
    for tool_id, stage_key in result.all():
        mapping.setdefault(tool_id, []).append(stage_key)
    return mapping


async def list_tools(db: AsyncSession) -> list[dict[str, Any]]:
    """列出所有外部工具（密钥脱敏，并附带各工具已绑定的 stage_key）."""
    result = await db.execute(select(ExternalTool).order_by(ExternalTool.created_at.desc()))
    rows = result.scalars().all()
    bound_map = await _load_bound_stage_map(db, [t.id for t in rows])
    return [_tool_to_view(t, bound_map.get(t.id)) for t in rows]


async def create_tool(
    db: AsyncSession,
    name: str,
    preset: str = "custom",
    tool_type: str = "http_search",
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_ms: int = 10000,
    max_query_chars: int = 400,
    enabled: bool = True,
) -> dict[str, Any]:
    """新建外部工具：密钥加密入库，base_url 做 SSRF 校验."""
    api_key_enc: str | None = None
    if api_key is not None and api_key.strip():
        key = api_key.strip()
        _reject_masked_key("api_key", key)
        api_key_enc = encrypt_secret(key)

    if base_url:
        new_base = base_url.strip()
        if new_base:
            _validate_api_base(new_base, "base_url")
            base_url = new_base
    else:
        base_url = None

    tool = ExternalTool(
        name=name,
        preset=preset,
        tool_type=tool_type,
        api_key_enc=api_key_enc,
        base_url=base_url,
        timeout_ms=timeout_ms,
        max_query_chars=max_query_chars,
        enabled=enabled,
        version=1,
    )
    db.add(tool)
    await db.flush()
    return _tool_to_view(tool)


async def update_tool(
    db: AsyncSession,
    tool_id: uuid.UUID,
    expected_version: int,
    name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_ms: int | None = None,
    max_query_chars: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """更新外部工具：三态密钥 + 乐观锁 version=expected.

    密钥三态：None=保持原值、""=清除（置 NULL）、非空=更新（+拒收脱敏串）。
    乐观锁：传入 expected_version，与 DB 中 version 不匹配 → ConflictError(409)。
    """
    result = await db.execute(select(ExternalTool).where(ExternalTool.id == tool_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise NotFoundError("外部工具")

    # 乐观锁校验
    if tool.version != expected_version:
        raise ConflictError("工具已被其他操作修改，请刷新后重试")

    if name is not None:
        tool.name = name

    # 三态密钥
    if api_key is not None:
        new_key = api_key.strip()
        if new_key:
            _reject_masked_key("api_key", new_key)
            tool.api_key_enc = encrypt_secret(new_key)
        else:
            # 空串 → 清除
            tool.api_key_enc = None

    # base_url（三态语义：None=保持、""=清除、非空=更新+SSRF 校验）
    if base_url is not None:
        new_base = base_url.strip() or None
        if new_base:
            _validate_api_base(new_base, "base_url")
        tool.base_url = new_base

    if timeout_ms is not None:
        tool.timeout_ms = timeout_ms

    if max_query_chars is not None:
        tool.max_query_chars = max_query_chars

    if enabled is not None:
        tool.enabled = enabled

    # 乐观锁版本号递增
    tool.version = expected_version + 1

    await db.flush()
    return _tool_to_view(tool)


async def delete_tool(db: AsyncSession, tool_id: uuid.UUID) -> None:
    """删除外部工具（级联删除绑定）."""
    result = await db.execute(select(ExternalTool).where(ExternalTool.id == tool_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise NotFoundError("外部工具")
    await db.delete(tool)
    await db.flush()


async def test_tool(db: AsyncSession, tool_id: uuid.UUID) -> list[dict[str, Any]]:
    """连通性测试：调 call_external_tool 传 "test" 查询."""
    result = await db.execute(select(ExternalTool).where(ExternalTool.id == tool_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise NotFoundError("外部工具")

    api_key: str | None = None
    if tool.api_key_enc:
        api_key = _decrypt_or_empty(tool.api_key_enc)

    return await call_external_tool(tool, api_key, "test")


async def bind_stage(db: AsyncSession, tool_id: uuid.UUID, stage_key: str) -> dict[str, Any]:
    """绑定工具到阶段：白名单校验 → 不在白名单 ValidationError(422 语义)."""
    # 白名单校验
    allowed_types = STAGE_TOOL_WHITELIST.get(stage_key)
    if allowed_types is None or "http_search" not in allowed_types:
        raise ValidationError(f"阶段 '{stage_key}' 不支持绑定外部工具")

    # 工具存在性校验
    result = await db.execute(select(ExternalTool).where(ExternalTool.id == tool_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise NotFoundError("外部工具")

    # 幂等：已存在则跳过
    existing = await db.execute(
        select(StageToolBinding).where(
            StageToolBinding.tool_id == tool_id,
            StageToolBinding.stage_key == stage_key,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {"toolId": str(tool_id), "stageKey": stage_key, "bound": True}

    binding = StageToolBinding(tool_id=tool_id, stage_key=stage_key)
    db.add(binding)
    await db.flush()
    return {"toolId": str(tool_id), "stageKey": stage_key, "bound": True}


async def unbind_stage(db: AsyncSession, tool_id: uuid.UUID, stage_key: str) -> None:
    """解绑工具与阶段."""
    result = await db.execute(
        select(StageToolBinding).where(
            StageToolBinding.tool_id == tool_id,
            StageToolBinding.stage_key == stage_key,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is not None:
        await db.delete(binding)
        await db.flush()


async def list_bindings(db: AsyncSession, stage_key: str | None = None) -> list[dict[str, Any]]:
    """列出绑定关系（可选按 stage_key 过滤）."""
    stmt = select(StageToolBinding)
    if stage_key is not None:
        stmt = stmt.where(StageToolBinding.stage_key == stage_key)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [{"toolId": str(b.tool_id), "stageKey": b.stage_key} for b in rows]


def invalidate_tools_cache() -> None:
    """清空外部工具定义缓存."""
    invalidate()
