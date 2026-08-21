"""评分对标 API — 阶段 D（SDD §3.4：对标表读写）.

GET /projects/{pid}/benchmark：项目成员读对标表（懒计算 coverage/risk 并回写）。
PUT /projects/{pid}/benchmark/{clause_no}/strategy：仅 owner 编辑应对策略
（审计 benchmark.strategy）。DB 操作统一委托 benchmark_service（批次 1a 分层重构）。
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.response import success
from app.services import benchmark_service
from app.services.project_service import _check_project_member

router = APIRouter()


class StrategyBody(BaseModel):
    """应对策略编辑请求体."""

    strategy: str = Field("", max_length=2000)


@router.get("/{project_id}/benchmark")
async def get_benchmark(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """评分对标表（项目成员可见）：懒计算 coverage/risk 并回写 risk_level."""
    await _check_project_member(db, project_id, user_id)
    items = await benchmark_service.build_benchmark(db, project_id)
    await db.commit()  # risk_level 懒回写
    return success(data={"items": items})


@router.put("/{project_id}/benchmark/{clause_no}/strategy")
async def update_benchmark_strategy(
    project_id: uuid.UUID,
    clause_no: str,
    body: StrategyBody,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑评分点应对策略（仅 owner；审计 benchmark.strategy）."""
    sp = await benchmark_service.update_strategy(db, project_id, clause_no, body.strategy)
    await audit.record(
        db,
        owner_id,
        "benchmark.strategy",
        project_id=project_id,
        target_type="score_point",
        target_id=str(sp.id),
        detail={"clause_no": clause_no},
    )
    await db.commit()
    return success(data={"clause_no": clause_no, "strategy": sp.strategy or ""})
