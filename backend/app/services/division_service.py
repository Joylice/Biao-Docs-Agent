"""章节分工服务 — 分配 upsert、分工列表、章节级编辑权限判定."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAssignment, ProposalSection
from app.models.user import User

ASSIGNMENT_STATUSES = ("pending", "in_progress", "submitted", "approved", "rejected")


async def _is_project_member(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """成员归属判定：owner 或 project_members 在表."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project and project.owner_id == user_id:
        return True
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return member_result.scalar_one_or_none() is not None


async def assign_chapters(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> list[ChapterAssignment]:
    """批量分配章节负责人（幂等 upsert）.

    items: [{chapter_no, title, assignee_id}]；已分配章节更新负责人并重置为 pending。
    assignee 必须是项目成员，否则 4004。
    """
    assignments: list[ChapterAssignment] = []
    for item in items:
        chapter_no = str(item.get("chapter_no") or "").strip()
        title = str(item.get("title") or "").strip()
        assignee_raw = item.get("assignee_id")
        if not chapter_no or not title or not assignee_raw:
            raise BizError(code=4000, message="分工条目缺少 chapter_no/title/assignee_id")
        try:
            assignee_id = uuid.UUID(str(assignee_raw))
        except ValueError:
            raise BizError(code=4000, message="assignee_id 格式错误") from None

        if not await _is_project_member(db, project_id, assignee_id):
            raise BizError(code=4004, message=f"章节 {chapter_no} 的负责人不是项目成员")

        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == chapter_no,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment:
            # 重新分配：更新负责人并重置流转状态
            assignment.title = title
            assignment.assignee_id = assignee_id
            assignment.assigned_by = owner_id
            assignment.status = "pending"
            assignment.review_comment = None
            assignment.assigned_at = datetime.now(UTC)
            assignment.accepted_at = None
            assignment.submitted_at = None
            assignment.reviewed_at = None
        else:
            assignment = ChapterAssignment(
                project_id=project_id,
                chapter_no=chapter_no,
                title=title,
                assignee_id=assignee_id,
                assigned_by=owner_id,
                status="pending",
            )
            db.add(assignment)
        assignments.append(assignment)
    await db.flush()
    return assignments


async def list_assignments(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """分工列表：含负责人 display_name 与章节内容状态（proposal_sections.status）."""
    result = await db.execute(
        select(ChapterAssignment, User, ProposalSection.status)
        .join(User, User.id == ChapterAssignment.assignee_id)
        .outerjoin(
            ProposalSection,
            (ProposalSection.project_id == ChapterAssignment.project_id)
            & (ProposalSection.section_id == ChapterAssignment.chapter_no),
        )
        .where(ChapterAssignment.project_id == project_id)
        .order_by(ChapterAssignment.chapter_no)
    )

    def _iso(ts: datetime | None) -> str | None:
        return ts.isoformat() if ts else None

    items: list[dict[str, Any]] = []
    for assignment, user, section_status in result.all():
        items.append(
            {
                "id": str(assignment.id),
                "chapter_no": assignment.chapter_no,
                "title": assignment.title,
                "assignee_id": str(assignment.assignee_id),
                "assignee_name": user.display_name or user.email,
                "assigned_by": str(assignment.assigned_by),
                "status": assignment.status,
                "section_status": section_status,
                "review_comment": assignment.review_comment,
                "assigned_at": _iso(assignment.assigned_at),
                "accepted_at": _iso(assignment.accepted_at),
                "submitted_at": _iso(assignment.submitted_at),
                "reviewed_at": _iso(assignment.reviewed_at),
            }
        )
    return items


async def get_assignment(
    db: AsyncSession, project_id: uuid.UUID, assignment_id: uuid.UUID
) -> ChapterAssignment | None:
    """按 id 读取项目内的分工记录."""
    result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.id == assignment_id,
            ChapterAssignment.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def check_chapter_editable(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID,
    is_owner: bool = False,
) -> bool:
    """章节级编辑权限（可视不可改）.

    已分配章节仅 assignee/owner 可编辑；未分配章节保持现状（项目成员可编辑）。
    """
    result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.project_id == project_id,
            ChapterAssignment.chapter_no == chapter_no,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return True
    if is_owner or assignment.assignee_id == user_id:
        return True
    # 兜底：调用方未传 is_owner 时查项目 owner 判定
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    return bool(project and project.owner_id == user_id)
