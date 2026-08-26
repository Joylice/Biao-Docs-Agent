"""工作台 API — 单端点返回双视图数据（个人待办分桶 + 参与项目进度；owner 追加待审核）.

聚合查询委托 workbench_service（批次 1b 分层重构）。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.services.project import workbench_service

router = APIRouter()


@router.get("/summary")
async def workbench_summary(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """工作台聚合：我的任务分桶 + 参与项目进度；owner 追加名下项目进度与待审核清单.

    全部基于 chapter_assignments 聚合查询（项目阶段附 proposal_workflows.phase）；
    my_projects = 我参与的（名下有分工）∪ owner 名下项目；
    owner 项目进度看板每项目一条（计划 §阶段 C，无分工项目 total=0）；
    非 owner 的 owner_review_pending 为空列表（前端按角色渲染双视图）。
    """
    data = await workbench_service.get_summary(db, user_id)
    return success(data=data)
