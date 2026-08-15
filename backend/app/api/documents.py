"""文档管理 API 路由."""

import io
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError, ValidationError
from app.core.response import paginated, success
from app.models.document import Document, ScorePoint, TechRequirement
from app.schemas.document import (
    DocumentListOut,
    DocumentUploadOut,
    ScorePointOut,
    ScorePointUpdate,
    TechRequirementOut,
)
from app.services import task_service
from app.services.project_service import _check_project_member
from app.services.storage_service import upload_file

router = APIRouter()


@router.post("/{project_id}/documents")
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile,
    doc_type: str = Query(..., description="tender_file|kb_material"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传文档（招标文件或资料库素材）."""
    await _check_project_member(db, project_id, user_id)

    # 校验文件类型
    if file.content_type not in settings.allowed_upload_types:
        raise ValidationError(f"不支持的文件类型: {file.content_type}")

    # 校验文件大小
    content = await file.read()
    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise ValidationError(f"文件大小超过限制 ({settings.max_upload_size_mb}MB)")

    # 上传到 MinIO
    storage_key = upload_file(
        io.BytesIO(content),
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        project_id=project_id,
    )

    # 登记文档记录
    doc = Document(
        project_id=project_id,
        doc_type=doc_type,
        title=file.filename or "unknown",
        storage_key=storage_key,
        status="uploaded",
        created_by=user_id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # 审计埋点：文档上传（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.upload",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
        detail={"title": doc.title, "doc_type": doc_type, "size_bytes": len(content)},
    )

    # 异步任务入队：解析/向量化由 worker 推进状态；Redis 不可用时降级不阻断上传
    if doc_type == "tender_file":
        await task_service.enqueue_parse_tender(project_id, doc.id)
    elif doc_type == "kb_material":
        await task_service.enqueue_index_document(project_id, doc.id)

    return success(data=DocumentUploadOut.model_validate(doc).model_dump(mode="json"))


@router.get("/{project_id}/documents")
async def list_documents(
    project_id: uuid.UUID,
    doc_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """文档列表."""
    await _check_project_member(db, project_id, user_id)

    query = select(Document).where(Document.project_id == project_id)
    if doc_type:
        query = query.where(Document.doc_type == doc_type)

    # 总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页
    items_query = (
        query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    result = await db.execute(items_query)
    items = list(result.scalars().all())

    items_data = [DocumentListOut.model_validate(d).model_dump(mode="json") for d in items]
    return paginated(items_data, total)


@router.get("/{project_id}/score-points")
async def list_score_points(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """评分点列表."""
    await _check_project_member(db, project_id, user_id)

    result = await db.execute(
        select(ScorePoint).where(ScorePoint.project_id == project_id).order_by(ScorePoint.clause_no)
    )
    items = list(result.scalars().all())
    items_data = [ScorePointOut.model_validate(sp).model_dump(mode="json") for sp in items]
    return success(data=items_data)


@router.put("/{project_id}/score-points/{sp_id}")
async def update_score_point(
    project_id: uuid.UUID,
    sp_id: uuid.UUID,
    req: ScorePointUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新评分点（人工编辑 strategy 或确认）."""
    await _check_project_member(db, project_id, user_id)

    result = await db.execute(
        select(ScorePoint).where(ScorePoint.id == sp_id, ScorePoint.project_id == project_id)
    )
    sp = result.scalar_one_or_none()
    if not sp:
        raise BizError(code=4004, message="评分点不存在")

    if req.strategy is not None:
        sp.strategy = req.strategy
    if req.confirmed is not None:
        sp.confirmed = req.confirmed

    await db.flush()
    await db.refresh(sp)
    return success(data=ScorePointOut.model_validate(sp).model_dump(mode="json"))


@router.get("/{project_id}/tech-requirements")
async def list_tech_requirements(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """技术需求列表."""
    await _check_project_member(db, project_id, user_id)

    result = await db.execute(
        select(TechRequirement)
        .where(TechRequirement.project_id == project_id)
        .order_by(TechRequirement.seq)
    )
    items = list(result.scalars().all())
    items_data = [TechRequirementOut.model_validate(tr).model_dump(mode="json") for tr in items]
    return success(data=items_data)
