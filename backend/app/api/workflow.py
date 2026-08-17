"""工作流 API 路由 — LangGraph 编排控制（经 workflow_runtime 服务层）."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError
from app.core.response import success
from app.services import workflow_runtime
from app.services.project_service import _check_project_member

router = APIRouter()


class ConfirmOutlineBody(BaseModel):
    """确认大纲请求体 — outline 为前端修改后的大纲（可选）；

    mounted_doc_ids 为资料库挂载配置（可选）：非 None（含空列表）时写入工作流
    state，缺省 None 保持项目全量检索。
    """

    outline: list[dict] | None = None
    mounted_doc_ids: list[uuid.UUID] | None = None


class OutlineDraftBody(BaseModel):
    """大纲二次编辑草稿请求体 — outline 为树形嵌套编辑产物."""

    outline: list[dict]
    mounted_doc_ids: list[uuid.UUID] | None = None


class ConfirmReviewBody(BaseModel):
    """确认审阅请求体 — approved 通过 / feedback 携带 {chapter_no: comment} 修改意见."""

    action: Literal["approved", "feedback"] = "approved"
    feedback: dict[str, str] = {}


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
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认/修改大纲（编辑后大纲与挂载配置经 resume payload 传递，
    不经 update_state — 避免清除 checkpoint pending interrupt）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_outline")

    decision: dict = {"confirmed": True}
    if body is not None:
        if body.outline is not None:
            decision["outline"] = body.outline
        if body.mounted_doc_ids is not None:
            decision["mounted_doc_ids"] = [str(x) for x in body.mounted_doc_ids]
    workflow_runtime.resume_workflow_in_background(project_id, decision)
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
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存大纲二次编辑草稿（成员可写；留审计）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.save_outline_draft(
        db,
        project_id,
        body.outline,
        [str(x) for x in body.mounted_doc_ids] if body.mounted_doc_ids is not None else None,
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
        return success(data={"outline": [], "mounted_doc_ids": None, "updated_at": None})
    return success(data=draft)


@router.delete("/{project_id}/workflow/outline-draft")
async def clear_outline_draft(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """清除大纲二次编辑草稿（确认成功后前端调用；幂等；留审计）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.clear_outline_draft(db, project_id)
    # 审计埋点：草稿清除（security.md §4）
    await audit.record(db, user_id, "workflow.outline_draft_clear", project_id=project_id)
    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()
    return success(data={"cleared": True})


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

    # 审计埋点：审阅确认（security.md §4）
    await audit.record(db, user_id, "workflow.confirm_review", project_id=project_id)

    # 事务约定（BUG-1）：审计写入响应前显式提交
    await db.commit()

    workflow_runtime.resume_workflow_in_background(project_id, decision)
    next_phase = "export" if decision["action"] == "approved" else "rewrite"
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
