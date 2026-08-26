"""LLM 配置页面化 API 路由（全局配置，无项目上下文）.

安全门禁：
- GET 永不返回密钥明文（脱敏 + configured 标志），普通登录用户可读；
- PUT / POST /test 仅管理员可调（get_current_admin_id，BID_ADMIN_USER_IDS，C-1）；
- PUT 审计 detail 只记变更字段名（core.audit 另有敏感键兜底剔除）。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_admin_id, get_current_user_id
from app.core.response import success
from app.schemas.settings import LlmSettingsTestRequest, LlmSettingsUpdate
from app.services.infra import settings_service

router = APIRouter()


@router.get("/llm")
async def get_llm_settings_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读取 LLM 页面配置（密钥脱敏展示）."""
    view = await settings_service.get_settings_view(db)
    return success(data=view)


@router.put("/llm")
async def update_llm_settings_api(
    req: LlmSettingsUpdate,
    user_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新 LLM 页面配置（仅管理员；密钥三态：None=保持/""=清除/非空=更新；加密入库）."""
    changed = await settings_service.update_llm_settings(db, req)

    # 审计埋点：detail 只记变更字段名，不含密钥明文（security.md §4）
    await audit.record(
        db,
        user_id,
        "settings.llm_update",
        target_type="llm_settings",
        detail={"fields": changed},
    )

    # 事务约定（BUG-1）：配置 + 审计同事务，响应前显式提交
    await db.commit()

    # W-1：commit 成功后再失效运行时缓存（本进程即时生效；worker 靠 TTL 收敛）
    settings_service.invalidate_runtime_cache()

    return success(message="LLM 配置已更新")


@router.post("/llm/test")
async def test_llm_settings_api(
    req: LlmSettingsTestRequest,
    user_id: uuid.UUID = Depends(get_current_admin_id),
) -> dict:
    """连通性测试（仅管理员）：真实调用 LLM/Embedding；业务结果在 data.ok，异常不上抛."""
    result = await settings_service.test_connection(req.target)
    return success(data=result)
