"""LLM 配置页面化 API 路由（全局配置，无项目上下文）.

安全门禁：
- GET 永不返回密钥明文（脱敏 + configured 标志），普通登录用户可读；
- PUT / POST /test 仅管理员可调（get_current_admin_id，BID_ADMIN_USER_IDS，C-1）；
- PUT 审计 detail 只记变更字段名（core.audit 另有敏感键兜底剔除）。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id, get_current_user_id
from app.core.response import success
from app.schemas.settings import (
    LlmSettingsTestRequest,
    LlmSettingsUpdate,
    ProviderCreate,
    ProviderUpdate,
    RetrievalConfigUpdate,
    RouteUpdate,
)
from app.services.infra import settings_service

router = APIRouter()


# === Legacy LLM Settings (llm_settings 表) ===


@router.get("/llm")
async def get_llm_settings_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取 LLM 页面配置（密钥脱敏展示）."""
    view = await settings_service.get_settings_view(db)
    return success(data=view)


@router.put("/llm")
async def update_llm_settings_api(
    req: LlmSettingsUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新 LLM 页面配置（仅管理员；密钥三态：None=保持/""=清除/非空=更新；加密入库）."""
    changed = await settings_service.update_llm_settings(db, req)

    await audit.record(
        db,
        user_id,
        "settings.llm_update",
        target_type="llm_settings",
        detail={"fields": changed},
    )

    await db.commit()
    settings_service.invalidate_runtime_cache()

    return success(message="LLM 配置已更新")


@router.post("/llm/test")
async def test_llm_settings_api(
    req: LlmSettingsTestRequest,
    user_id: uuid.UUID = Depends(get_current_admin_id),
) -> dict[str, Any]:
    """连通性测试（仅管理员）：真实调用 LLM/Embedding；业务结果在 data.ok，异常不上抛.

    携带覆盖字段（model/api_base）时按表单未保存值测试，SSRF 校验与保存路径同源。
    """
    overrides: dict[str, str] | None = None
    if req.target == "llm" and (req.model is not None or req.api_base is not None):
        if req.api_base:
            settings_service.validate_llm_api_base(req.api_base)
        overrides = {
            "model": req.model or "",
            "api_base": req.api_base or "",
            "api_key": req.api_key or "",
        }
    result = await settings_service.test_connection(req.target, overrides)
    return success(data=result)


# === Provider Registry (llm_providers 表) ===


@router.get("/providers")
async def list_providers_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出所有 LLM 服务商（密钥脱敏）."""
    providers = await settings_service.list_providers(db)
    return success(data=providers)


@router.post("/providers")
async def create_provider_api(
    req: ProviderCreate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建服务商（仅管理员）."""
    provider = await settings_service.create_provider(db, req)

    await audit.record(
        db,
        user_id,
        "settings.provider_create",
        target_type="llm_provider",
        detail={"name": req.name, "prefix": req.prefix},
    )
    await db.commit()
    settings_service.invalidate_runtime_cache()

    return success(data=provider, message="服务商已添加")


@router.put("/providers/{provider_id}")
async def update_provider_api(
    provider_id: uuid.UUID,
    req: ProviderUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新服务商（仅管理员；密钥三态）."""
    provider = await settings_service.update_provider(db, provider_id, req)

    await audit.record(
        db,
        user_id,
        "settings.provider_update",
        target_type="llm_provider",
        detail={
            "provider_id": str(provider_id),
            "fields": list(req.model_dump(exclude_unset=True).keys()),
        },
    )
    await db.commit()
    settings_service.invalidate_runtime_cache()

    return success(data=provider, message="服务商已更新")


@router.delete("/providers/{provider_id}")
async def delete_provider_api(
    provider_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除服务商（仅管理员；内置不可删）."""
    await settings_service.delete_provider(db, provider_id)

    await audit.record(
        db,
        user_id,
        "settings.provider_delete",
        target_type="llm_provider",
        detail={"provider_id": str(provider_id)},
    )
    await db.commit()
    settings_service.invalidate_runtime_cache()

    return success(message="服务商已删除")


# === Model Routes (model_routes 表) ===


@router.get("/routes")
async def list_routes_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出所有模型路由."""
    routes = await settings_service.list_routes(db)
    return success(data=routes)


@router.put("/routes/{stage_key}")
async def update_route_api(
    stage_key: str,
    req: RouteUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新单个路由（仅管理员）."""
    route = await settings_service.update_route(db, stage_key, req)

    await audit.record(
        db,
        user_id,
        "settings.route_update",
        target_type="model_route",
        detail={"stage": stage_key, "fields": list(req.model_dump(exclude_unset=True).keys())},
    )
    await db.commit()
    settings_service.invalidate_runtime_cache()

    return success(data=route, message="路由已更新")


# === Retrieval Config (retrieval_configs 表) ===


@router.get("/retrieval")
async def get_retrieval_config_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取检索参数配置（rerank 密钥脱敏展示）."""
    view = await settings_service.get_retrieval_config_view(db)
    return success(data=view)


@router.put("/retrieval")
async def update_retrieval_config_api(
    req: RetrievalConfigUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新检索参数配置（仅管理员；rerank_api_key 三态：None=保持/""=清除/非空=更新）."""
    changed = await settings_service.update_retrieval_config(db, req)

    await audit.record(
        db,
        user_id,
        "settings.retrieval_update",
        target_type="retrieval_config",
        detail={"fields": changed},
    )
    await db.commit()

    return success(message="检索参数已更新")


# === Reindex (重建索引) ===


@router.post("/retrieval/reindex")
async def reindex_all_api(
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """触发全量索引重建（仅管理员；异步 arq 任务执行，返回 job 入队状态）."""
    from app.services.project.task_service import enqueue_reindex_all

    enqueued = await enqueue_reindex_all()

    await audit.record(
        db,
        user_id,
        "settings.reindex_triggered",
        target_type="retrieval_config",
        detail={"enqueued": enqueued},
    )
    await db.commit()

    if enqueued:
        return success(message="索引重建任务已入队，后台执行中")
    return success(
        message="索引重建入队失败（Redis 不可用），请稍后重试或检查 Worker 服务",
        data={"enqueued": False},
    )
