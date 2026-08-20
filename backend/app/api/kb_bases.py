"""知识库 API 路由 — 多知识库容器管理（个人/项目/公司三级可见性）.

设计（2026-08-18）：知识库为素材（kb_material）的分组与授权容器，不改变
分块/向量链路；方案生成挂载由 confirm-outline 的 mounted_kb_ids 传入。
"""

import contextlib
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError, NotFoundError
from app.core.response import paginated, success
from app.models.document import Document
from app.models.knowledge_base import SCOPE_PROJECT, VALID_SCOPES, KnowledgeBase
from app.models.project import Project
from app.models.user import User
from app.schemas.document import DocumentListOut
from app.services import kb_base_service, storage_service

router = APIRouter()


class KbBaseCreateIn(BaseModel):
    """创建知识库请求体."""

    scope: str  # personal|project|company
    name: str
    description: str | None = None
    project_id: uuid.UUID | None = None


class KbBaseUpdateIn(BaseModel):
    """编辑知识库请求体（name/description 均可选）."""

    name: str | None = None
    description: str | None = None


async def _get_base_or_404(db: AsyncSession, base_id: uuid.UUID) -> KnowledgeBase:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == base_id))
    base = result.scalar_one_or_none()
    if not base:
        raise NotFoundError("知识库")
    return base


def _base_out(
    base: KnowledgeBase, material_count: int = 0, project_name: str | None = None
) -> dict:
    return {
        "id": str(base.id),
        "name": base.name,
        "description": base.description,
        "scope": base.scope,
        "project_id": str(base.project_id) if base.project_id else None,
        "project_name": project_name,
        "owner_id": str(base.owner_id) if base.owner_id else None,
        "material_count": material_count,
        "created_at": base.created_at.isoformat() if base.created_at else None,
    }


@router.get("/kb-bases")
async def list_kb_bases(
    project_id: uuid.UUID | None = Query(None, description="项目上下文（返回该项目的项目库）"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """可见知识库列表（公司全员 / 个人仅本人 / 项目限成员）."""
    items = await kb_base_service.list_visible_bases(db, user_id, project_id)
    return success(data={"items": items, "total": len(items)})


@router.post("/kb-bases")
async def create_kb_base(
    req: KbBaseCreateIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建知识库（personal 任意登录用户 / project 仅 owner / company 仅管理员）."""
    if req.scope not in VALID_SCOPES:
        raise BizError(code=4000, message=f"scope 非法：{req.scope}")
    base = await kb_base_service.create_base(
        db,
        user_id,
        scope=req.scope,
        name=req.name,
        description=req.description,
        project_id=req.project_id,
    )
    await audit.record(
        db,
        user_id,
        "kb.base_create",
        project_id=base.project_id,
        target_type="knowledge_base",
        target_id=str(base.id),
        detail={"scope": base.scope, "name": base.name},
    )
    await db.commit()
    project_name: str | None = None
    if base.project_id:
        p_result = await db.execute(select(Project).where(Project.id == base.project_id))
        project = p_result.scalar_one_or_none()
        project_name = project.name if project else None
    return success(data=_base_out(base, project_name=project_name))


@router.patch("/kb-bases/{base_id}")
async def update_kb_base(
    base_id: uuid.UUID,
    req: KbBaseUpdateIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑知识库（名称/描述；写权限按 scope 判定）."""
    base = await _get_base_or_404(db, base_id)
    await kb_base_service.check_base_writable(db, base, user_id)

    changed: list[str] = []
    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise BizError(code=4000, message="知识库名称不能为空")
        base.name = new_name
        changed.append("name")
    if req.description is not None:
        base.description = req.description.strip() or None
        changed.append("description")

    await audit.record(
        db,
        user_id,
        "kb.base_update",
        project_id=base.project_id,
        target_type="knowledge_base",
        target_id=str(base.id),
        detail={"changed": changed},
    )
    await db.commit()
    return success(data=_base_out(base))


@router.delete("/kb-bases/{base_id}")
async def delete_kb_base(
    base_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除知识库（写权限按 scope 判定；库内素材一并删除：MinIO + 记录 + 分块 CASCADE）."""
    base = await _get_base_or_404(db, base_id)
    await kb_base_service.check_base_writable(db, base, user_id)

    docs_result = await db.execute(
        select(Document).where(Document.kb_id == base.id, Document.doc_type == "kb_material")
    )
    docs = list(docs_result.scalars().all())
    for doc in docs:
        with contextlib.suppress(Exception):
            storage_service.delete_file(doc.storage_key)
        await db.delete(doc)

    await audit.record(
        db,
        user_id,
        "kb.base_delete",
        project_id=base.project_id,
        target_type="knowledge_base",
        target_id=str(base.id),
        detail={"name": base.name, "scope": base.scope, "material_count": len(docs)},
    )
    await db.delete(base)
    await db.commit()
    return success(data={"id": str(base_id)})


@router.get("/kb-bases/{base_id}/materials")
async def list_kb_base_materials(
    base_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """库内素材列表（复用全局素材列表口径，限可见库）."""
    base = await _get_base_or_404(db, base_id)
    # 可见性校验：个人库仅本人；项目库限成员；公司库全员
    if base.scope == "personal" and base.owner_id != user_id:
        raise NotFoundError("知识库")
    if base.scope == SCOPE_PROJECT and (
        base.project_id is None
        or not await kb_base_service.is_project_member(db, base.project_id, user_id)
    ):
        raise NotFoundError("知识库")

    query = (
        select(Document, User.display_name)
        .join(User, Document.created_by == User.id, isouter=True)
        .where(Document.kb_id == base.id, Document.doc_type == "kb_material")
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = []
    for doc, uploader_name in result.all():
        item = DocumentListOut.model_validate(doc).model_dump(mode="json")
        item["uploader_name"] = uploader_name or ""
        items.append(item)
    return paginated(items, total)
