"""工作流 API 路由 — LangGraph 编排控制（经 workflow_runtime 服务层）."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.exceptions import BizError, ForbiddenError
from app.core.response import success
from app.models.project import ProjectMember
from app.models.proposal import ChapterAssignment
from app.services import division_service, workflow_runtime
from app.services.event_service import publish_event, publish_user_event
from app.services.project_service import _check_project_member

router = APIRouter()


class ConfirmOutlineBody(BaseModel):
    """确认大纲请求体 — outline 为前端修改后的大纲（可选）；

    mounted_doc_ids 为资料库挂载配置（可选）：非 None（含空列表）时写入工作流
    state，缺省 None 保持项目全量检索；mounted_kb_ids 为知识库级挂载（2026-08-18，
    与文档级并集生效）。
    """

    outline: list[dict] | None = None
    mounted_doc_ids: list[uuid.UUID] | None = None
    mounted_kb_ids: list[uuid.UUID] | None = None


class OutlineDraftBody(BaseModel):
    """大纲二次编辑草稿请求体 — outline 为树形嵌套编辑产物."""

    outline: list[dict]
    mounted_doc_ids: list[uuid.UUID] | None = None
    mounted_kb_ids: list[uuid.UUID] | None = None


class ConfirmReviewBody(BaseModel):
    """确认审阅请求体 — approved 通过 / feedback 携带 {chapter_no: comment} 修改意见."""

    action: Literal["approved", "feedback"] = "approved"
    feedback: dict[str, str] = {}


class SectionEditBody(BaseModel):
    """章节人工编辑请求体 — content 为编辑后的 Markdown 正文."""

    content: str


class OutlineSuggestApplyBody(BaseModel):
    """采纳大纲建议请求体 — adopted 为勾选的 suggestion_id 列表."""

    adopted: list[str]


class SectionSuggestBody(BaseModel):
    """内容改进建议请求体 — chapter_no 可选，限定分析章节."""

    chapter_no: str | None = None


@router.post("/{project_id}/workflow/start")
async def start_workflow(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启动投标方案生成工作流（后台推进图执行，遇 HITL interrupt 停下）."""
    await _check_project_member(db, project_id, user_id)

    # 审计埋点：工作流启动（security.md §4）
    await audit.record(db, user_id, "workflow.start", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()

    workflow_runtime.start_workflow_in_background(project_id, user_id)
    status = await workflow_runtime.get_status_dict(project_id)
    return success(
        data={
            "workflow_id": str(project_id),
            "status": "started",
            **status,
        }
    )


@router.get("/{project_id}/workflow/status")
async def get_workflow_status(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取工作流状态（从 checkpointer 读取最新 checkpoint）."""
    await _check_project_member(db, project_id, user_id)

    return success(data=await workflow_runtime.get_status_dict(project_id))


@router.post("/{project_id}/workflow/confirm-score-points")
async def confirm_score_points(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认评分点（resume confirm_score_points interrupt，后台推进）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_score_points")

    workflow_runtime.resume_workflow_in_background(project_id, {"confirmed": True})
    return success(data={"status": "confirmed", "next_phase": "outline"})


@router.post("/{project_id}/workflow/confirm-outline")
async def confirm_outline(
    project_id: uuid.UUID,
    body: ConfirmOutlineBody | None = None,
    user_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认/修改大纲（仅 owner；编辑后大纲与挂载配置经 resume payload 传递，
    不经 update_state — 避免清除 checkpoint pending interrupt）."""
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_outline")

    decision: dict = {"confirmed": True}
    if body is not None:
        if body.outline is not None:
            decision["outline"] = body.outline
        if body.mounted_doc_ids is not None:
            decision["mounted_doc_ids"] = [str(x) for x in body.mounted_doc_ids]
        if body.mounted_kb_ids is not None:
            decision["mounted_kb_ids"] = [str(x) for x in body.mounted_kb_ids]
    workflow_runtime.resume_workflow_in_background(project_id, decision)
    # 阶段 C：大纲确认后通知全体成员刷新工作台（用户级频道，去重含 owner）
    members_result = await db.execute(
        select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    )
    targets = {str(uid) for uid in members_result.scalars().all()} | {str(user_id)}
    for uid in targets:
        await publish_user_event(
            uid, {"type": "workbench_refresh", "project_id": str(project_id)}
        )
    return success(data={"status": "confirmed", "next_phase": "generate"})


@router.post("/{project_id}/workflow/regenerate-outline")
async def regenerate_outline(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重新生成大纲 — 仅限 confirm_outline 挂起时（覆盖旧大纲，新提示词含 covered_clauses）."""
    await _check_project_member(db, project_id, user_id)
    try:
        outline = await workflow_runtime.regenerate_outline(project_id)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5011, message=f"重新生成大纲失败: {e}") from None
    return success(data={"status": "regenerated", "outline": outline})


@router.put("/{project_id}/workflow/outline-draft")
async def save_outline_draft(
    project_id: uuid.UUID,
    body: OutlineDraftBody,
    user_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存大纲二次编辑草稿（仅 owner 可写；留审计）."""
    await workflow_runtime.save_outline_draft(
        db,
        project_id,
        body.outline,
        [str(x) for x in body.mounted_doc_ids] if body.mounted_doc_ids is not None else None,
        [str(x) for x in body.mounted_kb_ids] if body.mounted_kb_ids is not None else None,
    )
    # 审计埋点：草稿保存（security.md §4）
    await audit.record(db, user_id, "workflow.outline_draft_save", project_id=project_id)
    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"saved": True})


@router.get("/{project_id}/workflow/outline-draft")
async def get_outline_draft(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读取大纲二次编辑草稿（成员可读；无草稿返回 outline=[]）."""
    await _check_project_member(db, project_id, user_id)
    draft = await workflow_runtime.get_outline_draft(db, project_id)
    if draft is None:
        return success(
            data={
                "outline": [],
                "mounted_doc_ids": None,
                "mounted_kb_ids": None,
                "updated_at": None,
            }
        )
    return success(data=draft)


@router.delete("/{project_id}/workflow/outline-draft")
async def clear_outline_draft(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """清除大纲二次编辑草稿（仅 owner；确认成功后前端调用；幂等；留审计）."""
    await workflow_runtime.clear_outline_draft(db, project_id)
    # 审计埋点：草稿清除（security.md §4）
    await audit.record(db, user_id, "workflow.outline_draft_clear", project_id=project_id)
    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"cleared": True})


async def _redispatch_feedback(
    db: AsyncSession, project_id: uuid.UUID, feedback: dict[str, str]
) -> dict[str, str]:
    """审阅意见回派章节/子节负责人（阶段 5）.

    feedback 键支持章级/子节编号或标题匹配（子节编号/标题来自大纲嵌套树）：
    - 命中分工 → assignment 置 rejected + 意见落库 + 推送 task_reviewed
      （assignee 在分工页「我的任务」看到打回可重编）；
    - 子节无分工时降级匹配父章分工；
    - 无分工章节 → 保留原 rewrite 链路。
    返回未被回派的剩余 feedback（避免重复重写）。
    """
    if not feedback:
        return {}
    from app.services.chapter_service import numbered_sections

    snapshot = await workflow_runtime.get_state(project_id)
    outline = (snapshot.values or {}).get("outline", []) or []
    nos: set[str] = set()
    title_to_no: dict[str, str] = {}
    for c in outline:
        no = str(c.get("chapter_no", ""))
        nos.add(no)
        title_to_no[str(c.get("title", ""))] = no
        # 子节编号/标题同样参与匹配（嵌套树推导，与分工编号规则一致）
        for sub_no, sub_title in numbered_sections(c.get("sections", []) or [], no):
            nos.add(sub_no)
            title_to_no.setdefault(sub_title, sub_no)
    remaining: dict[str, str] = {}
    for key, comment in feedback.items():
        chapter_no = key if key in nos else title_to_no.get(key, "")
        if not chapter_no:
            remaining[key] = comment
            continue
        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == chapter_no,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment is None and "." in chapter_no:
            # 子节无分工 → 降级回派父章负责人（章级分工覆盖子节）
            parent_no = chapter_no.rsplit(".", 1)[0]
            result = await db.execute(
                select(ChapterAssignment).where(
                    ChapterAssignment.project_id == project_id,
                    ChapterAssignment.chapter_no == parent_no,
                )
            )
            assignment = result.scalar_one_or_none()
        if assignment is None:
            remaining[key] = comment
            continue
        assignment.status = "rejected"
        assignment.review_comment = comment
        assignment.reviewed_at = datetime.now(UTC)
        await publish_event(
            str(project_id),
            {
                "type": "task_reviewed",
                "chapter_no": chapter_no,
                "assignee_id": str(assignment.assignee_id),
                "action": "rejected",
            },
        )
    await db.flush()
    # 事务约定（BUG-1）：回派状态在 resume 前显式提交，assignee 立即可见打回
    await db.commit()
    return remaining


@router.post("/{project_id}/workflow/confirm-review")
async def confirm_review(
    project_id: uuid.UUID,
    body: ConfirmReviewBody | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认审阅（resume review interrupt：approved → 导出 / feedback → 重写后复审）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "review_request")

    decision = (
        {"action": body.action, "feedback": body.feedback}
        if body
        else {"action": "approved", "feedback": {}}
    )

    # 意见回派：命中分工的章节退回负责人重编，不再走 rewrite；无分工保持原链路
    if decision["action"] == "feedback" and decision["feedback"]:
        decision["feedback"] = await _redispatch_feedback(db, project_id, decision["feedback"])
        # 全部意见均已回派负责人 → 无需 AI 重写，保持审阅中等待重编后复审
        if not decision["feedback"]:
            decision["action"] = "redispatched"

    # 审计埋点：审阅确认（security.md §4）
    await audit.record(db, user_id, "workflow.confirm_review", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()

    workflow_runtime.resume_workflow_in_background(project_id, decision)
    if decision["action"] == "approved":
        next_phase = "export"
    elif decision["action"] == "redispatched":
        next_phase = "redispatch"
    else:
        next_phase = "rewrite"
    return success(
        data={"status": "confirmed", "action": decision["action"], "next_phase": next_phase}
    )


@router.post("/{project_id}/workflow/rewrite-chapter")
async def rewrite_chapter(
    project_id: uuid.UUID,
    chapter_no: str,
    comment: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """根据审阅意见重写章节（从 state 取原文，结果经 checkpointer 回写）."""
    await _check_project_member(db, project_id, user_id)

    try:
        new_content = await workflow_runtime.rewrite_chapter(project_id, chapter_no, comment)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5011, message=f"章节重写失败: {e}") from None
    return success(data={"chapter_no": chapter_no, "content": new_content})


@router.put("/{project_id}/workflow/sections/{chapter_no}")
async def save_section_edit(
    project_id: uuid.UUID,
    chapter_no: str,
    body: SectionEditBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工编辑章节内容直接落库（state + proposal_sections 同步）.

    章节级编辑权限（可视不可改）：已分配章节仅 assignee/owner 可编辑，
    未分配章节保持现状（项目成员可编辑）。
    """
    await _check_project_member(db, project_id, user_id)
    if not await division_service.check_chapter_editable(db, project_id, chapter_no, user_id):
        raise ForbiddenError("无权编辑该章节（已分配章节仅负责人/项目负责人可编辑）")

    try:
        await workflow_runtime.save_section_edit(db, project_id, chapter_no, body.content)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5011, message=f"章节保存失败: {e}") from None

    # 审计埋点：章节人工编辑（security.md §4）
    await audit.record(db, user_id, "workflow.section_edit", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"chapter_no": chapter_no, "saved": True})


@router.post("/{project_id}/workflow/outline-suggest")
async def outline_suggest(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成大纲优化建议（仅 confirm_outline 挂起时可用；建议为瞬态数据不落库）."""
    from app.services.outline_suggest_service import build_outline_suggestions

    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_outline")

    status = await workflow_runtime.get_status_dict(project_id)
    suggestions = await build_outline_suggestions(status["score_points"], status["outline"])

    # 审计埋点：大纲建议生成（security.md §4）
    await audit.record(db, user_id, "workflow.outline_suggest", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"suggestions": suggestions})


@router.post("/{project_id}/workflow/outline-suggest/apply")
async def outline_suggest_apply(
    project_id: uuid.UUID,
    body: OutlineSuggestApplyBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """应用已采纳的大纲建议 — 仅返回调整后大纲供人工核对，不写 state.

    最终执行仍由 confirm-outline 人工确认完成（确认后才生成章节）。
    """
    from app.services.outline_suggest_service import apply_outline_suggestions

    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_outline")

    status = await workflow_runtime.get_status_dict(project_id)
    outline = apply_outline_suggestions(status["outline"], body.adopted)

    # 审计埋点：大纲建议采纳（security.md §4）
    await audit.record(db, user_id, "workflow.outline_suggest_apply", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"outline": outline})


@router.post("/{project_id}/workflow/section-suggest")
async def section_suggest(
    project_id: uuid.UUID,
    body: SectionSuggestBody | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成内容改进建议（建议为瞬态数据不落库；采纳执行复用 rewrite-chapter）."""
    from app.services.section_suggest_service import build_section_suggestions

    await _check_project_member(db, project_id, user_id)

    status = await workflow_runtime.get_status_dict(project_id)
    suggestions = await build_section_suggestions(
        status["chapters"],
        status["score_points"],
        chapter_no=body.chapter_no if body else None,
    )

    # 审计埋点：内容建议生成（security.md §4）
    await audit.record(db, user_id, "workflow.section_suggest", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"suggestions": suggestions})


@router.get("/{project_id}/workflow/export")
async def export_document(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """导出 Word 文档（复用图内 export 节点逻辑，返回下载信息）."""
    await _check_project_member(db, project_id, user_id)

    # 审计埋点：方案导出（security.md §4）
    await audit.record(db, user_id, "workflow.export", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()

    try:
        result = await workflow_runtime.export_workflow(project_id)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5010, message=f"导出失败: {e}") from None
    return success(data=result)
