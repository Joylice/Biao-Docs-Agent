"""工作流 API 路由 — LangGraph 编排控制."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError
from app.core.response import success
from app.services.project_service import _check_project_member

router = APIRouter()


@router.post("/{project_id}/workflow/start")
async def start_workflow(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启动投标方案生成工作流."""
    await _check_project_member(db, project_id, user_id)

    # 审计埋点：工作流启动（security.md §4）
    await audit.record(db, user_id, "workflow.start", project_id=project_id)

    # TODO: 使用 LangGraph checkpointer 持久化状态
    # 目前使用内存状态，后续接入 PostgresSaver

    return success(
        data={
            "workflow_id": str(uuid.uuid4()),
            "status": "started",
            "phase": "init",
        }
    )


@router.get("/{project_id}/workflow/status")
async def get_workflow_status(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取工作流状态."""
    await _check_project_member(db, project_id, user_id)

    # TODO: 从 checkpointer 读取状态
    return success(
        data={
            "phase": "init",
            "progress": 0.0,
            "score_points": [],
            "outline": [],
            "chapters": {},
            "review_comments": [],
            "export_status": "",
        }
    )


@router.post("/{project_id}/workflow/confirm-score-points")
async def confirm_score_points(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认评分点."""
    await _check_project_member(db, project_id, user_id)

    # TODO: 更新 checkpointer 中的状态，resume workflow
    return success(data={"status": "confirmed", "next_phase": "outline"})


@router.post("/{project_id}/workflow/confirm-outline")
async def confirm_outline(
    project_id: uuid.UUID,
    outline: list[dict] | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工确认/修改大纲."""
    await _check_project_member(db, project_id, user_id)

    # TODO: 更新 checkpointer 中的状态，resume workflow
    return success(data={"status": "confirmed", "next_phase": "generate"})


@router.post("/{project_id}/workflow/rewrite-chapter")
async def rewrite_chapter(
    project_id: uuid.UUID,
    chapter_no: str,
    comment: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """根据审阅意见重写章节."""
    await _check_project_member(db, project_id, user_id)

    from app.services.review_service import rewrite_chapter

    try:
        new_content = await rewrite_chapter(
            chapter_no=chapter_no,
            original_content="",  # TODO: 从状态中获取
            comment=comment,
        )
        return success(data={"chapter_no": chapter_no, "content": new_content})
    except Exception as e:
        raise BizError(code=5011, message=f"章节重写失败: {e}") from None


@router.get("/{project_id}/workflow/export")
async def export_document(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """导出 Word 文档."""
    await _check_project_member(db, project_id, user_id)

    # 审计埋点：方案导出（security.md §4）
    await audit.record(db, user_id, "workflow.export", project_id=project_id)

    # TODO: 从状态中获取章节内容，调用 export_to_word
    return success(data={"export_status": "pending"})
