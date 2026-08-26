"""章节级批注 API — 阶段 E5（chapters/{no}/annotations CRUD）.

写权限复用 check_chapter_editable 口径（章节 assignee/项目 owner）；
编辑/删除进一步限批注作者本人或项目 owner（判定在 annotation_service 内）。
DB 操作统一委托 annotation_service（批次 1a 分层重构）。
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import ForbiddenError
from app.core.response import success
from app.services.project import annotation_service
from app.services.project.division_service import check_chapter_editable
from app.services.project.project_service import _check_project_member

router = APIRouter()


class AnnotationBody(BaseModel):
    """批注内容请求体."""

    content: str = Field(..., min_length=1, max_length=2000)


async def _check_write_permission(
    db: AsyncSession, project_id: uuid.UUID, chapter_no: str, user_id: uuid.UUID
) -> None:
    await _check_project_member(db, project_id, user_id)
    if not await check_chapter_editable(db, project_id, chapter_no, user_id):
        raise ForbiddenError("无该章节批注权限（仅章节负责人/项目负责人可写）")


@router.get("/{project_id}/chapters/{chapter_no}/annotations")
async def list_chapter_annotations(
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """章节批注列表（项目成员可读，按时间正序）."""
    await _check_project_member(db, project_id, user_id)
    items = await annotation_service.list_annotations(db, project_id, chapter_no)
    return success(data={"items": items})


@router.post("/{project_id}/chapters/{chapter_no}/annotations")
async def create_chapter_annotation(
    project_id: uuid.UUID,
    chapter_no: str,
    body: AnnotationBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增章节批注（章节负责人/项目负责人可写）."""
    await _check_write_permission(db, project_id, chapter_no, user_id)
    data = await annotation_service.create_annotation(
        db, project_id, chapter_no, body.content, user_id
    )
    await audit.record(
        db,
        user_id,
        "annotation.create",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=data["id"],
        detail={"chapter_no": chapter_no},
    )
    await db.commit()
    return success(data=data)


@router.put("/{project_id}/chapters/{chapter_no}/annotations/{annotation_id}")
async def update_chapter_annotation(
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
    body: AnnotationBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑章节批注（作者本人或项目负责人）."""
    await _check_write_permission(db, project_id, chapter_no, user_id)
    data = await annotation_service.update_annotation(
        db, project_id, chapter_no, annotation_id, body.content, user_id
    )
    await audit.record(
        db,
        user_id,
        "annotation.update",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=data["id"],
    )
    await db.commit()
    return success(data=data)


@router.delete("/{project_id}/chapters/{chapter_no}/annotations/{annotation_id}")
async def delete_chapter_annotation(
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除章节批注（作者本人或项目负责人）."""
    await _check_write_permission(db, project_id, chapter_no, user_id)
    ann_id = await annotation_service.delete_annotation(
        db, project_id, chapter_no, annotation_id, user_id
    )
    await audit.record(
        db,
        user_id,
        "annotation.delete",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=ann_id,
    )
    await db.commit()
    return success(data={"id": str(annotation_id)})
