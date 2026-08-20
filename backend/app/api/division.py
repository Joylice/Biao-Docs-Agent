"""章节分工协作 API — 分配/列表/领取/生成初稿/提交（审核端点见后续）."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.exceptions import BizError, ForbiddenError, NotFoundError, ValidationError
from app.core.response import success
from app.models.project import Project
from app.models.proposal import ChapterAnnotation
from app.models.user import User
from app.services import division_service, version_service, workflow_runtime
from app.services.event_service import publish_event, publish_user_event
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


class AssistGenerateBody(BaseModel):
    """AI 辅助生成请求体（阶段 2）：prompt 自定义提示词，mode=append 追加/overwrite 覆盖."""

    prompt: str = ""
    mode: Literal["append", "overwrite"] = "append"


class AnnotationBody(BaseModel):
    """章节批注请求体（阶段 4）."""

    content: str = Field(..., min_length=1)


@router.get("/{project_id}/chapter-assignments")
async def list_chapter_assignments(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分工列表（项目成员可见，可视不可改的「可视」入口）.

    附 outline 子节（sections）供前端 2 级目录展示（分工粒度仍为章级）。
    """
    await _check_project_member(db, project_id, user_id)
    items = await division_service.list_assignments(db, project_id)
    snapshot = await workflow_runtime.get_state(project_id)
    outline = (snapshot.values or {}).get("outline", []) or []
    sections_map = {str(c.get("chapter_no", "")): c.get("sections", []) for c in outline}
    for item in items:
        item["sections"] = sections_map.get(item["chapter_no"], [])
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
    # 阶段 C：定向推送到各 assignee 用户频道（工作台待办实时刷新，去重）
    for assignee_id in {a.assignee_id for a in assignments}:
        await publish_user_event(
            str(assignee_id),
            {
                "type": "task_assigned",
                "project_id": str(project_id),
                "assignments": [
                    {"chapter_no": a.chapter_no, "assignee_id": str(a.assignee_id)}
                    for a in assignments
                    if a.assignee_id == assignee_id
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


@router.post("/{project_id}/chapter-assignments/{assignment_id}/assist-generate")
async def assist_generate_assignment(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssistGenerateBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI 辅助生成（仅 assignee）：知识库检索 + 章节上下文 + 自定义提示词，流式经 WS
    section_token（source=assist）推送，可经 stop 端点暂停（已生成部分按 mode 落库）."""
    from app.services import assist_service

    assignment = await _load_my_assignment(db, project_id, assignment_id, user_id)
    if assignment.status not in ("in_progress", "rejected"):
        raise ValidationError("请先领取任务后再辅助生成")
    try:
        result = await assist_service.assist_generate(
            project_id,
            assignment.chapter_no,
            user_id,
            prompt=body.prompt,
            mode=body.mode,
        )
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5011, message=f"辅助生成失败: {e}") from None
    await audit.record(
        db,
        user_id,
        "division.assist_generate",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
        detail={"mode": body.mode, "stopped": result["stopped"]},
    )
    await db.commit()
    return success(
        data={
            "id": str(assignment.id),
            "chapter_no": assignment.chapter_no,
            "content": result["content"],
            "stopped": result["stopped"],
            "mode": result["mode"],
        }
    )


@router.post("/{project_id}/chapter-assignments/{assignment_id}/assist-generate/stop")
async def stop_assist_generate(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """暂停辅助生成（仅 assignee）：置位取消令牌，生成端点保留已生成部分后返回."""
    from app.services import assist_service

    assignment = await _load_my_assignment(db, project_id, assignment_id, user_id)
    stopped = assist_service.stop_task(project_id, assignment.chapter_no)
    return success(data={"id": str(assignment.id), "stopped": stopped})


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
    # 阶段 C：提交待审 → 定向推送项目 owner（待审核待办）
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is not None:
        await publish_user_event(
            str(project.owner_id),
            {
                "type": "task_submitted",
                "project_id": str(project_id),
                "chapter_no": assignment.chapter_no,
                "assignee_id": str(assignment.assignee_id),
                "assignment_id": str(assignment.id),
            },
        )
    return success(data={"id": str(assignment.id), "status": assignment.status})


@router.get("/{project_id}/chapter-assignments/{assignment_id}/annotations")
async def list_annotations(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """章节批注列表（项目成员可读，按时间正序）."""
    await _check_project_member(db, project_id, user_id)
    assignment = await division_service.get_assignment(db, project_id, assignment_id)
    if assignment is None:
        raise NotFoundError("分工记录")
    result = await db.execute(
        select(ChapterAnnotation, User.display_name)
        .join(User, User.id == ChapterAnnotation.created_by)
        .where(
            ChapterAnnotation.project_id == project_id,
            ChapterAnnotation.chapter_no == assignment.chapter_no,
        )
        .order_by(ChapterAnnotation.created_at.asc())
    )
    items = [
        {
            "id": str(ann.id),
            "chapter_no": ann.chapter_no,
            "content": ann.content,
            "created_by": str(ann.created_by),
            "created_by_name": name or "",
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        }
        for ann, name in result.all()
    ]
    return success(data={"items": items})


@router.post("/{project_id}/chapter-assignments/{assignment_id}/annotations")
async def create_annotation(
    project_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AnnotationBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增章节批注（assignee 或项目 owner 可写），与审核打回意见字段并存."""
    await _check_project_member(db, project_id, user_id)
    assignment = await division_service.get_assignment(db, project_id, assignment_id)
    if assignment is None:
        raise NotFoundError("分工记录")
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    is_owner = project is not None and project.owner_id == user_id
    if assignment.assignee_id != user_id and not is_owner:
        raise ForbiddenError("仅章节负责人或项目负责人可批注")

    ann = ChapterAnnotation(
        project_id=project_id,
        chapter_no=assignment.chapter_no,
        content=body.content.strip(),
        created_by=user_id,
    )
    db.add(ann)
    await db.flush()
    await db.refresh(ann)
    await audit.record(
        db,
        user_id,
        "division.annotate",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=str(ann.id),
    )
    # 事务约定（BUG-1）：写入 + 审计响应前显式提交
    await db.commit()
    return success(
        data={
            "id": str(ann.id),
            "chapter_no": ann.chapter_no,
            "content": ann.content,
            "created_by": str(ann.created_by),
        }
    )


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
    # 阶段 C：审核结果 → 定向推送 assignee（打回/通过待办变更）
    await publish_user_event(
        str(assignment.assignee_id),
        {
            "type": "task_reviewed",
            "project_id": str(project_id),
            "chapter_no": assignment.chapter_no,
            "assignee_id": str(assignment.assignee_id),
            "action": body.action,
        },
    )
    # 审核通过后检查自动快照条件（全部章节定稿 → 版本库自动入库；失败不阻塞审核）
    if body.action == "approved":
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is not None:
            await version_service.maybe_auto_snapshot(db, project_id, project.name)
    return success(data={"id": str(assignment.id), "status": assignment.status})
