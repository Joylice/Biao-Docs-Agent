"""工作台 API — 单端点返回双视图数据（个人待办分桶 + 参与项目进度；owner 追加待审核）."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.models.project import Project
from app.models.proposal import ChapterAssignment, ProposalWorkflow

router = APIRouter()

# 任务分桶（assignment 状态 → 待领取/编制中/被打回/已提审/已通过）
TASK_BUCKETS = ("pending", "in_progress", "rejected", "submitted", "approved")


def _task_item(assignment: ChapterAssignment, project_name: str) -> dict[str, Any]:
    """分工行 → 待办条目（含项目名与章节号，前端直达分工页）."""
    return {
        "assignment_id": str(assignment.id),
        "project_id": str(assignment.project_id),
        "project_name": project_name,
        "chapter_no": assignment.chapter_no,
        "title": assignment.title,
        "status": assignment.status,
    }


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
    # 我负责的全部分工（join 项目取名；跨项目一次查回）
    result = await db.execute(
        select(ChapterAssignment, Project.name)
        .join(Project, Project.id == ChapterAssignment.project_id)
        .where(ChapterAssignment.assignee_id == user_id)
    )
    tasks: dict[str, list[dict[str, Any]]] = {b: [] for b in TASK_BUCKETS}
    projects: dict[uuid.UUID, dict[str, Any]] = {}
    for assignment, project_name in result.all():
        bucket = tasks.setdefault(assignment.status, [])
        bucket.append(_task_item(assignment, project_name))
        proj = projects.setdefault(
            assignment.project_id,
            {
                "project_id": str(assignment.project_id),
                "project_name": project_name,
                "total": 0,
                "approved": 0,
                "percent": 0,
                "phase": "",
                "status_dist": {b: 0 for b in TASK_BUCKETS},
            },
        )
        proj["total"] += 1
        if assignment.status == "approved":
            proj["approved"] += 1
        proj["status_dist"][assignment.status] = (
            proj["status_dist"].get(assignment.status, 0) + 1
        )

    def _upsert_project(project_id: uuid.UUID, project_name: str) -> dict[str, Any]:
        """项目聚合行幂等 upsert（我参与 ∪ owner 名下共用）."""
        return projects.setdefault(
            project_id,
            {
                "project_id": str(project_id),
                "project_name": project_name,
                "total": 0,
                "approved": 0,
                "percent": 0,
                "phase": "",
                "status_dist": {b: 0 for b in TASK_BUCKETS},
            },
        )

    # owner 视图：名下项目全部纳入进度看板（LEFT JOIN 分工，无分工项目 total=0）
    owner_result = await db.execute(
        select(Project, ChapterAssignment)
        .join(
            ChapterAssignment,
            ChapterAssignment.project_id == Project.id,
            isouter=True,
        )
        .where(Project.owner_id == user_id)
    )
    for project, assignment in owner_result.all():
        proj = _upsert_project(project.id, project.name)
        if assignment is None:
            continue
        proj["total"] += 1
        if assignment.status == "approved":
            proj["approved"] += 1
        proj["status_dist"][assignment.status] = (
            proj["status_dist"].get(assignment.status, 0) + 1
        )

    # 项目阶段（proposal_workflows.phase，无工作流行 → 空串）
    if projects:
        wf_result = await db.execute(
            select(ProposalWorkflow).where(
                ProposalWorkflow.project_id.in_(list(projects.keys()))
            )
        )
        for wf in wf_result.scalars().all():
            if wf.project_id in projects:
                projects[wf.project_id]["phase"] = wf.phase

    my_projects: list[dict[str, Any]] = []
    for proj in projects.values():
        proj["percent"] = round(proj["approved"] / proj["total"] * 100) if proj["total"] else 0
        my_projects.append(proj)

    # owner 视图：名下项目待审核（submitted）清单；非 owner 为空
    review_result = await db.execute(
        select(ChapterAssignment, Project.name)
        .join(Project, Project.id == ChapterAssignment.project_id)
        .where(Project.owner_id == user_id, ChapterAssignment.status == "submitted")
    )
    owner_review_pending = [_task_item(a, name) for a, name in review_result.all()]

    return success(
        data={
            "tasks": tasks,
            "my_projects": my_projects,
            "owner_review_pending": owner_review_pending,
        }
    )
