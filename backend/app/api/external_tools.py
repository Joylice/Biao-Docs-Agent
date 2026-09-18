"""外部工具管理 API 路由（挂 /settings/external-tools 前缀）.

安全门禁：
- GET 普通用户可读（脱敏），写操作仅管理员（get_current_admin_id）；
- 每写操作后 await db.commit() + tools_service.invalidate_tools_cache()；
- 审计 detail 只记字段名/工具 ID（不含密钥明文）。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id, get_current_user_id
from app.core.response import success
from app.schemas.external_tools import BindBody, ToolCreate, ToolUpdate
from app.services.infra.tools import tools_service

router = APIRouter()


@router.get("")
async def list_tools_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出所有外部工具（密钥脱敏，普通用户可读）."""
    tools = await tools_service.list_tools(db)
    return success(data=tools)


@router.post("")
async def create_tool_api(
    req: ToolCreate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建外部工具（仅管理员；密钥加密入库）."""
    tool = await tools_service.create_tool(
        db,
        name=req.name,
        preset=req.preset,
        tool_type=req.tool_type,
        api_key=req.api_key,
        base_url=req.base_url,
        timeout_ms=req.timeout_ms,
        max_query_chars=req.max_query_chars,
        enabled=req.enabled,
    )

    await audit.record(
        db,
        user_id,
        "settings.external_tool_create",
        target_type="external_tool",
        detail={"name": req.name, "preset": req.preset},
    )
    await db.commit()
    tools_service.invalidate_tools_cache()

    return success(data=tool, message="外部工具已添加")


@router.put("/{tool_id}")
async def update_tool_api(
    tool_id: uuid.UUID,
    req: ToolUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新外部工具（仅管理员；密钥三态 + 乐观锁）."""
    tool = await tools_service.update_tool(
        db,
        tool_id,
        expected_version=req.expected_version,
        name=req.name,
        api_key=req.api_key,
        base_url=req.base_url,
        timeout_ms=req.timeout_ms,
        max_query_chars=req.max_query_chars,
        enabled=req.enabled,
    )

    changed_fields = [
        k
        for k, v in req.model_dump(exclude_unset=True).items()
        if k != "expected_version" and v is not None
    ]
    await audit.record(
        db,
        user_id,
        "settings.external_tool_update",
        target_type="external_tool",
        detail={"tool_id": str(tool_id), "fields": changed_fields},
    )
    await db.commit()
    tools_service.invalidate_tools_cache()

    return success(data=tool, message="外部工具已更新")


@router.delete("/{tool_id}")
async def delete_tool_api(
    tool_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除外部工具（仅管理员；级联删除绑定）."""
    await tools_service.delete_tool(db, tool_id)

    await audit.record(
        db,
        user_id,
        "settings.external_tool_delete",
        target_type="external_tool",
        detail={"tool_id": str(tool_id)},
    )
    await db.commit()
    tools_service.invalidate_tools_cache()

    return success(message="外部工具已删除")


@router.post("/{tool_id}/test")
async def test_tool_api(
    tool_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """连通性测试（仅管理员）：调 call_external_tool 传 "test" 查询."""
    result = await tools_service.test_tool(db, tool_id)
    return success(data=result)


@router.put("/{tool_id}/bind")
async def bind_stage_api(
    tool_id: uuid.UUID,
    req: BindBody,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """绑定工具到阶段（仅管理员；白名单校验）."""
    result = await tools_service.bind_stage(db, tool_id, req.stage_key)

    await audit.record(
        db,
        user_id,
        "settings.external_tool_bind",
        target_type="external_tool",
        detail={"tool_id": str(tool_id), "stage_key": req.stage_key},
    )
    await db.commit()
    tools_service.invalidate_tools_cache()

    return success(data=result, message="工具已绑定到阶段")


@router.delete("/{tool_id}/bind/{stage_key}")
async def unbind_stage_api(
    tool_id: uuid.UUID,
    stage_key: str,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """解绑工具与阶段（仅管理员）."""
    await tools_service.unbind_stage(db, tool_id, stage_key)

    await audit.record(
        db,
        user_id,
        "settings.external_tool_unbind",
        target_type="external_tool",
        detail={"tool_id": str(tool_id), "stage_key": stage_key},
    )
    await db.commit()
    tools_service.invalidate_tools_cache()

    return success(message="工具已从阶段解绑")
