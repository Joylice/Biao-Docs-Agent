"""章节分工协作 API — 分配/列表/领取/生成初稿/提交/章节内容读写（审核端点见后续）.

DB 操作统一委托 division_service（批次 1c 分层重构）；
本层保留路由/依赖注入/请求 schema/审计埋点/事件推送/显式 commit。
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.exceptions import BizError, ForbiddenError, NotFoundError, ValidationError
from app.core.response import success
from app.services.infra import workflow_runtime
from app.services.infra.event_service import publish_event, publish_user_event
from app.services.project import division_service, version_service
from app.services.project.project_service import _check_project_member

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


class ChapterContentBody(BaseModel):
    """章节内容保存请求体：content 可空串（已清空），content_html 可空."""

    content: str = Field(..., min_length=0)
    content_html: str | None = None


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
    await division_service.accept_assignment(db, assignment)
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
    from app.services.project import assist_service

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
    from app.services.project import assist_service

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
    await division_service.submit_assignment(db, assignment)
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
    project = await division_service.get_project(db, project_id)
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
    items = await division_service.list_annotations(db, project_id, assignment.chapter_no)
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
    ann = await division_service.create_annotation(
        db, project_id, assignment, body.content, user_id
    )
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
    """负责人审核：submitted → approved/rejected（rejected 回退可重编），推送 task_reviewed.

    审核通过（approved）时：分工编制内容回写工作流正式方案（state.chapters +
    proposal_sections，status=approved），供审阅页/Word 导出使用（2026-08-25）。
    """
    assignment = await division_service.get_assignment(db, project_id, assignment_id)
    if assignment is None:
        raise NotFoundError("分工记录")
    await division_service.review_assignment(db, assignment, body.action, body.comment)
    if body.action == "approved" and assignment.content:
        # 内容回写正式方案；flush 后由下方统一 commit 提交
        await workflow_runtime.sync_approved_chapter(
            db,
            project_id,
            assignment.chapter_no,
            assignment.content,
            assignment.content_html,
        )
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
        project = await division_service.get_project(db, project_id)
        if project is not None:
            await version_service.maybe_auto_snapshot(db, project_id, project.name)
    return success(data={"id": str(assignment.id), "status": assignment.status})


@router.get("/{project_id}/chapters/{chapter_no}/content")
async def get_chapter_content(
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读取章节内容（项目成员可读；chapter_no 无对应分工记录 4004）."""
    await _check_project_member(db, project_id, user_id)
    assignment = await division_service.get_assignment_by_chapter(db, project_id, chapter_no)
    if assignment is None:
        raise NotFoundError("章节分工")
    return success(data={"content": assignment.content, "content_html": assignment.content_html})


@router.put("/{project_id}/chapters/{chapter_no}/content")
async def save_chapter_content(
    project_id: uuid.UUID,
    chapter_no: str,
    body: ChapterContentBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存章节内容（项目成员可写）：Markdown + 富文本 HTML 双字段落库 + 审计 + commit."""
    await _check_project_member(db, project_id, user_id)
    assignment = await division_service.get_assignment_by_chapter(db, project_id, chapter_no)
    if assignment is None:
        raise NotFoundError("章节分工")
    await division_service.update_chapter_content(db, assignment, body.content, body.content_html)
    await audit.record(
        db,
        user_id,
        "chapter.content_update",
        project_id=project_id,
        target_type="chapter_assignment",
        target_id=str(assignment.id),
        detail={"chapter_no": chapter_no},
    )
    # 事务约定（BUG-1）：写入 + 审计响应前显式提交
    await db.commit()
    return success(
        data={
            "chapter_no": assignment.chapter_no,
            "content": assignment.content,
            "content_html": assignment.content_html,
        }
    )
