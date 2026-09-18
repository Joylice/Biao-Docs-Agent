"""LLM 用量 API — GET /usage/summary、GET /usage/trend（仅登录用户可读，Phase 1 T4）.

- /usage/summary：按 stage/model 聚合 llm_usage_log：调用次数/成功率/token 总量/平均延迟。
- /usage/trend：按 日期 × stage_key 聚合 token，供配置中心各智能体用量折线图使用。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.services.infra import usage_service

router = APIRouter()


@router.get("/usage/summary")
async def get_usage_summary(
    project_id: uuid.UUID | None = None,
    stage_key: str | None = None,
    days: int = Query(default=7, ge=0, le=365, description="统计窗口天数，0=全部历史"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """LLM 用量汇总（按 stage/model 聚合：次数/成功率/token/平均延迟）."""
    items = await usage_service.usage_summary(db, project_id, stage_key, days)
    return success(data={"items": items, "days": days})


@router.get("/usage/trend")
async def get_usage_trend(
    project_id: uuid.UUID | None = None,
    days: int = Query(default=30, ge=1, le=365, description="趋势窗口天数"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """各智能体 Token 用量按日趋势（配置中心折线图数据源）."""
    data = await usage_service.usage_trend(db, project_id, days)
    return success(data=data)
