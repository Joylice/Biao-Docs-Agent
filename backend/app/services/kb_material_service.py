"""全局资料库素材服务 — kb_material 文档的 DB 操作（批次 1b 自 api/kb.py 等下沉）.

资料库独立管理：project_id IS NULL = 全局共享资料。可见性过滤复用
kb_base_service.material_visibility_clause；MinIO/向量化编排保留在 api 层。
事务约定：写路径只 flush/delete 不 commit，由 api 层显式提交（BUG-1）。
"""

import uuid

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ValidationError
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import ProjectMember
from app.models.user import User
from app.services import kb_base_service


async def register_material(
    db: AsyncSession,
    *,
    title: str,
    storage_key: str,
    category: str | None,
    tags: list[str],
    kb_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> Document:
    """登记全局素材（project_id IS NULL；status=uploaded），flush/refresh 不 commit."""
    doc = Document(
        project_id=None,
        doc_type="kb_material",
        title=title,
        storage_key=storage_key,
        status="uploaded",
        category=category,
        tags=tags,
        kb_id=kb_id,
        created_by=user_id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def list_global_materials(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    category: str | None,
    tag: str | None,
    kb_id: uuid.UUID | None,
) -> tuple[list[tuple[Document, str | None]], int]:
    """全局资料库列表（仅 kb_material，project_id IS NULL；按知识库可见性过滤）.

    可见性（2026-08-18）：kb_id IS NULL 存量未归档 / 公司库全员 / 本人个人库 /
    用户所属项目的项目库；他人个人库素材不可见。
    返回 ((Document, uploader_name) 行列表, total)；按 created_at 倒序分页。
    """
    query = (
        select(Document, User.display_name)
        .join(User, Document.created_by == User.id, isouter=True)
        .outerjoin(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == KnowledgeBase.project_id)
            & (ProjectMember.user_id == user_id),
        )
        .where(Document.project_id.is_(None), Document.doc_type == "kb_material")
        .where(kb_base_service.material_visibility_clause(user_id, ProjectMember.user_id))
    )
    if kb_id is not None:
        query = query.where(Document.kb_id == kb_id)
    if category:
        query = query.where(Document.category == category)
    if tag:
        # PG JSON 包含匹配（tags @> '["tag"]'）；tags 列为 JSON 类型，@> 仅 jsonb 支持，
        # 需 cast 右侧表达式为 JSONB（SQLite 测试下 CAST 无害）
        query = query.where(cast(Document.tags, JSONB).op("@>")(cast([tag], JSONB)))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    items_query = (
        query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    result = await db.execute(items_query)
    return list(result.all()), total


async def get_global_material(db: AsyncSession, doc_id: uuid.UUID) -> Document:
    """取全局资料（查询限定 project_id IS NULL，隔离项目级文档），不存在 → 4004."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.project_id.is_(None))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise BizError(code=4004, message="资料不存在")
    return doc


async def update_material(
    db: AsyncSession,
    doc_id: uuid.UUID,
    *,
    title: str | None,
    category: str | None,
    tags: list[str] | None,
) -> tuple[Document, list[str]]:
    """编辑全局素材（title/category/tags 均可选）；返回 (doc, changed) 供审计留痕."""
    doc = await get_global_material(db, doc_id)

    changed: list[str] = []
    if title is not None:
        new_title = title.strip()
        if not new_title:
            raise ValidationError("标题不能为空")
        doc.title = new_title
        changed.append("title")
    if category is not None:
        doc.category = category
        changed.append("category")
    if tags is not None:
        doc.tags = tags
        changed.append("tags")
    return doc, changed


async def get_material_for_download(db: AsyncSession, doc_id: uuid.UUID) -> Document:
    """下载代理取件：仅全局 kb_material 可经此接口（项目级文档隔离），否则 4004."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.project_id is not None or doc.doc_type != "kb_material":
        raise BizError(code=4004, message="资料不存在")
    return doc


async def delete_material(db: AsyncSession, doc: Document) -> None:
    """删除文档记录（分块 CASCADE）；不 commit."""
    await db.delete(doc)


async def global_material_doc_ids(db: AsyncSession) -> list[uuid.UUID]:
    """全部全局资料的 doc_ids（检索范围；空列表 = 无全局资料 → 无命中）."""
    doc_result = await db.execute(
        select(Document.id).where(Document.project_id.is_(None), Document.doc_type == "kb_material")
    )
    return [row[0] for row in doc_result.all()]


async def list_base_materials(db: AsyncSession, base_id: uuid.UUID) -> list[Document]:
    """库内全部素材（kb_material；删库级联用）."""
    docs_result = await db.execute(
        select(Document).where(Document.kb_id == base_id, Document.doc_type == "kb_material")
    )
    return list(docs_result.scalars().all())


async def list_base_materials_paged(
    db: AsyncSession, base_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[tuple[Document, str | None]], int]:
    """库内素材分页列表（复用全局素材列表口径：LEFT JOIN 上传者名）."""
    query = (
        select(Document, User.display_name)
        .join(User, Document.created_by == User.id, isouter=True)
        .where(Document.kb_id == base_id, Document.doc_type == "kb_material")
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return list(result.all()), total
