"""章节级批注 API — 阶段 E5（chapters/{no}/annotations CRUD）.

写权限复用 check_chapter_editable 口径（章节 assignee/项目 owner）；
编辑/删除进一步限批注作者本人或项目 owner。
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.response import success
from app.models.project import Project
from app.models.proposal import ChapterAnnotation
from app.models.user import User
from app.services.division_service import check_chapter_editable
from app.services.project_service import _check_project_member

router = APIRouter()


class AnnotationBody(BaseModel):
    """批注内容请求体."""

    content: str = Field(..., min_length=1, max_length=2000)


async def _get_annotation(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
) -> ChapterAnnotation:
    result = await db.execute(
        select(ChapterAnnotation).where(
            ChapterAnnotation.id == annotation_id,
            ChapterAnnotation.project_id == project_id,
            ChapterAnnotation.chapter_no == chapter_no,
        )
    )
    ann = result.scalar_one_or_none()
    if ann is None:
        raise NotFoundError("批注")
    return ann


async def _check_author_or_owner(
    db: AsyncSession, project_id: uuid.UUID, ann: ChapterAnnotation, user_id: uuid.UUID
) -> None:
    """批注修改权限：作者本人或项目 owner."""
    if ann.created_by == user_id:
        return
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None or project.owner_id != user_id:
        raise ForbiddenError("仅批注作者或项目负责人可修改")


async def _check_write_permission(
    db: AsyncSession, project_id: uuid.UUID, chapter_no: str, user_id: uuid.UUID
) -> None:
    await _check_project_member(db, project_id, user_id)
    if not await check_chapter_editable(db, project_id, chapter_no, user_id):
        raise ForbiddenError("无该章节批注权限（仅章节负责人/项目负责人可写）")


def _serialize(ann: ChapterAnnotation, author_name: str | None = None) -> dict:
    return {
        "id": str(ann.id),
        "chapter_no": ann.chapter_no,
        "content": ann.content,
        "created_by": str(ann.created_by),
        "created_by_name": author_name or "",
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
        "updated_at": ann.updated_at.isoformat() if ann.updated_at else None,
    }


@router.get("/{project_id}/chapters/{chapter_no}/annotations")
async def list_chapter_annotations(
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """章节批注列表（项目成员可读，按时间正序）."""
    await _check_project_member(db, project_id, user_id)
    result = await db.execute(
        select(ChapterAnnotation, User.display_name)
        .join(User, User.id == ChapterAnnotation.created_by)
        .where(
            ChapterAnnotation.project_id == project_id,
            ChapterAnnotation.chapter_no == chapter_no,
        )
        .order_by(ChapterAnnotation.created_at.asc())
    )
    items = [_serialize(ann, name) for ann, name in result.all()]
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
    ann = ChapterAnnotation(
        project_id=project_id,
        chapter_no=chapter_no,
        content=body.content.strip(),
        created_by=user_id,
    )
    db.add(ann)
    await db.flush()
    await db.refresh(ann)
    await audit.record(
        db,
        user_id,
        "annotation.create",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=str(ann.id),
        detail={"chapter_no": chapter_no},
    )
    await db.commit()
    return success(data=_serialize(ann))


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
    ann = await _get_annotation(db, project_id, chapter_no, annotation_id)
    await _check_author_or_owner(db, project_id, ann, user_id)
    ann.content = body.content.strip()
    await db.flush()
    await db.refresh(ann)
    await audit.record(
        db,
        user_id,
        "annotation.update",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=str(ann.id),
    )
    await db.commit()
    return success(data=_serialize(ann))


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
    ann = await _get_annotation(db, project_id, chapter_no, annotation_id)
    await _check_author_or_owner(db, project_id, ann, user_id)
    await audit.record(
        db,
        user_id,
        "annotation.delete",
        project_id=project_id,
        target_type="chapter_annotation",
        target_id=str(ann.id),
    )
    await db.delete(ann)
    await db.commit()
    return success(data={"id": str(annotation_id)})
