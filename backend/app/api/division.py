"""章节分工协作 API — 分配/列表/领取/生成初稿/提交（审核端点见后续）."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.exceptions import BizError, ForbiddenError, NotFoundError, ValidationError
from app.core.response import success
from app.services import division_service, workflow_runtime
from app.services.event_service import publish_event
from app.services.project_service import _check_project_member

router = APIRouter()


class AssignmentItem(BaseModel):
    """单条章节分工."""

    chapter_no: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1)
    assignee_id: uuid.UUID


class ReviewBody(BaseModel):
    """审核请求体：action=approved|rejected，rejected 时建议附意见."""

    action: Literal["approved", "rejected"]
    comment: str = ""


@router.get("/{project_id}/chapter-assignments")
async def list_chapter_assignments(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分工列表（项目成员可见，可视不可改的「可视」入口）."""
    await _check_project_member(db, project_id, user_id)
    items = await division_service.list_assignments(db, project_id)
    return success(data={"items": items})


@router.post("/{project_id}/chapter-assignments")
async def assign_chapters(
    project_id: uuid.UUID,
    body: list[AssignmentItem],
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量分配章节负责人（仅 owner；幂等 upsert；assignee 必须是项目成员）."""
    if not body:
        raise ValidationError("分工列表不能为空")
    assignments = await division_service.assign_chapters(
        db, project_id, owner_id, [item.model_dump(mode="json") for item in body]
    )
    await audit.record(
        db,
        owner_id,
        "division.assign",
        project_id=project_id,
        target_type="chapter_assignment",
        detail={"count": len(assignments)},
    )
    # 事务约定（BUG-1）：写入 + 审计响应前显式提交
    await db.commit()
    # 推送分工任务（WebSocket 转发，前端刷新分工列表）
    await publish_event(
        str(project_id),
        {
            "type": "task_assigned",
            "assignments": [
                {"chapter_no": a.chapter_no, "assignee_id": str(a.assignee_id)} for a in assignments
            ],
        },
    )
    items = await division_service.list_assignments(db, project_id)
    return success(data={"items": items})


async def _load_my_assignment(
    db: AsyncSession, project_id: uuid.UUID, assignment_id: uuid.UUID, user_id: uuid.UUID
):
    """载入分工记录并校验当前用户为 assignee（成员身份前置校验）."""
    await _check_project_member(db, project_id, user_id)
    assignment = await division_service.get_assignment(db, project_id, assignment_id)
    if assignment is None:
        raise NotFoundError("分工记录")
    if assignment.assignee_id != user_id:
        raise ForbiddenError("仅章节负责人可执行该操作")
    return assignment


@router.post("/{project_id}/chapter-assignments/{assignment_id}/accept")
async def accept_assignment(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """领取任务：pending/rejected → in_progress（仅 assignee）."""
    assignment = await _load_my_assignment(db, project_id, assignment_id, user_id)
    if assignment.status not in ("pending", "rejected"):
        raise ValidationError(f"当前状态 {assignment.status} 不可领取")
    assignment.status = "in_progress"
    assignment.accepted_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        user_id,
        "division.accept",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
    )
    await db.commit()
    return success(data={"id": str(assignment.id), "status": assignment.status})


@router.post("/{project_id}/chapter-assignments/{assignment_id}/generate")
async def generate_assignment_draft(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成章节初稿（仅 assignee；需先领取；复用 generate_chapter 链路，mock 可降级）."""
    assignment = await _load_my_assignment(db, project_id, assignment_id, user_id)
    if assignment.status not in ("in_progress", "rejected"):
        raise ValidationError("请先领取任务后再生成初稿")
    try:
        content = await workflow_runtime.generate_chapter_draft(project_id, assignment.chapter_no)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5011, message=f"章节初稿生成失败: {e}") from None
    await audit.record(
        db,
        user_id,
        "division.generate",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
    )
    await db.commit()
    return success(
        data={"id": str(assignment.id), "chapter_no": assignment.chapter_no, "content": content}
    )


@router.post("/{project_id}/chapter-assignments/{assignment_id}/submit")
async def submit_assignment(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交待审：in_progress/rejected → submitted（仅 assignee），推送 task_submitted."""
    assignment = await _load_my_assignment(db, project_id, assignment_id, user_id)
    if assignment.status not in ("in_progress", "rejected"):
        raise ValidationError(f"当前状态 {assignment.status} 不可提交")
    assignment.status = "submitted"
    assignment.submitted_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        user_id,
        "division.submit",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
    )
    await db.commit()
    await publish_event(
        str(project_id),
        {
            "type": "task_submitted",
            "chapter_no": assignment.chapter_no,
            "assignee_id": str(assignment.assignee_id),
            "assignment_id": str(assignment.id),
        },
    )
    return success(data={"id": str(assignment.id), "status": assignment.status})


@router.post("/{project_id}/chapter-assignments/{assignment_id}/review")
async def review_assignment(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: ReviewBody,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """负责人审核：submitted → approved/rejected（rejected 回退可重编），推送 task_reviewed."""
    assignment = await division_service.get_assignment(db, project_id, assignment_id)
    if assignment is None:
        raise NotFoundError("分工记录")
    if assignment.status != "submitted":
        raise ValidationError(f"当前状态 {assignment.status} 不可审核（仅待审章节可审核）")
    assignment.status = body.action
    assignment.review_comment = body.comment or None
    assignment.reviewed_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        owner_id,
        "division.review",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
        detail={"action": body.action},
    )
    await db.commit()
    await publish_event(
        str(project_id),
        {
            "type": "task_reviewed",
            "chapter_no": assignment.chapter_no,
            "assignee_id": str(assignment.assignee_id),
            "action": body.action,
        },
    )
    return success(data={"id": str(assignment.id), "status": assignment.status})
