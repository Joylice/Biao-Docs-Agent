"""章节级批注服务 — 阶段 E5（chapters/{no}/annotations CRUD 的 DB 操作）.

写权限（成员/章节可编辑）在 api 层校验；编辑/删除的「作者本人或项目 owner」
判定随 DB 读取一并下沉于此。事务约定：不 commit，由 api 层显式提交（BUG-1）。
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.project import Project
from app.models.proposal import ChapterAnnotation
from app.models.user import User


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


def _serialize(ann: ChapterAnnotation, author_name: str | None = None) -> dict:
    return {
        "id": str(ann.id),
        "chapter_no": ann.chapter_no,
        "content": ann.content,
        "status": ann.status or "open",
        "selection": ann.selection,
        "created_by": str(ann.created_by),
        "created_by_name": author_name or "",
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
        "updated_at": ann.updated_at.isoformat() if ann.updated_at else None,
    }


async def list_annotations(db: AsyncSession, project_id: uuid.UUID, chapter_no: str) -> list[dict]:
    """章节批注列表（JOIN 作者名，按时间正序）."""
    result = await db.execute(
        select(ChapterAnnotation, User.display_name)
        .join(User, User.id == ChapterAnnotation.created_by)
        .where(
            ChapterAnnotation.project_id == project_id,
            ChapterAnnotation.chapter_no == chapter_no,
        )
        .order_by(ChapterAnnotation.created_at.asc())
    )
    return [_serialize(ann, name) for ann, name in result.all()]


async def create_annotation(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    content: str,
    user_id: uuid.UUID,
    selection: dict[str, Any] | None = None,
) -> dict:
    """新增章节批注（内容去首尾空格；flush/refresh 后返回序列化项）."""
    ann = ChapterAnnotation(
        project_id=project_id,
        chapter_no=chapter_no,
        content=content.strip(),
        status="open",
        selection=selection,
        created_by=user_id,
    )
    db.add(ann)
    await db.flush()
    await db.refresh(ann)
    return _serialize(ann)


async def update_annotation(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
    content: str,
    user_id: uuid.UUID,
) -> dict:
    """编辑章节批注（作者本人或项目负责人；内容去首尾空格）."""
    ann = await _get_annotation(db, project_id, chapter_no, annotation_id)
    await _check_author_or_owner(db, project_id, ann, user_id)
    ann.content = content.strip()
    await db.flush()
    await db.refresh(ann)
    return _serialize(ann)


async def update_annotation_status(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
    status: str,
    user_id: uuid.UUID,
) -> dict:
    """更新批注状态（open/resolved）；项目成员均可操作."""
    if status not in ("open", "resolved"):
        raise NotFoundError("无效的批注状态")
    ann = await _get_annotation(db, project_id, chapter_no, annotation_id)
    # 状态切换不限制作者，项目成员均可
    ann.status = status
    await db.flush()
    await db.refresh(ann)
    # 查询作者名
    result = await db.execute(select(User.display_name).where(User.id == ann.created_by))
    author_name = result.scalar_one_or_none()
    return _serialize(ann, author_name)


async def delete_annotation(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    annotation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    """删除章节批注（作者本人或项目负责人）；返回被删批注 id 供审计留痕."""
    ann = await _get_annotation(db, project_id, chapter_no, annotation_id)
    await _check_author_or_owner(db, project_id, ann, user_id)
    await db.delete(ann)
    return str(ann.id)
