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
    """确认大纲请求体 — outline 为前端修改后的大纲（可选）."""

    outline: list[dict] | None = None


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
    """人工确认/修改大纲（修改后大纲先写回 state，再 resume confirm_outline interrupt）."""
    await _check_project_member(db, project_id, user_id)
    await workflow_runtime.ensure_pending_interrupt(project_id, "confirm_outline")

    outline = body.outline if body else None
    if outline:
        await workflow_runtime.update_state(project_id, {"outline": outline})
    workflow_runtime.resume_workflow_in_background(project_id, {"confirmed": True})
    return success(data={"status": "confirmed", "next_phase": "generate"})


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

    try:
        result = await workflow_runtime.export_workflow(project_id)
    except BizError:
        raise
    except Exception as e:
        raise BizError(code=5010, message=f"导出失败: {e}") from None
    return success(data=result)
