"""文档管理 API 路由."""

import io
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
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
from app.services import rag_service, task_service
from app.services.project_service import _check_project_member
from app.services.storage_service import presigned_url, upload_file

router = APIRouter()

# 章节插图：支持格式与大小上限（存 MinIO images/{project_id}/ 目录）
IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
IMAGE_MAX_SIZE_MB = 10

# 格式要求 category 枚举（与 parse.yaml 提示词对齐）；未知分类归入 other
FORMAT_REQUIREMENT_CATEGORIES = frozenset(
    {
        "font_body",
        "font_heading",
        "line_spacing",
        "margin",
        "page_setup",
        "binding",
        "page_number",
        "toc",
        "other",
    }
)


class FormatRequirementsBody(BaseModel):
    """格式要求保存请求体 — 完整数组幂等覆盖."""

    format_requirements: list[dict]


def _clean_format_requirements(items: list[dict]) -> list[dict]:
    """清洗格式要求条目：丢弃空 requirement，未知 category 归入 other."""
    cleaned: list[dict] = []
    for item in items:
        requirement = str(item.get("requirement") or "").strip()
        if not requirement:
            continue
        category = str(item.get("category") or "").strip()
        if category not in FORMAT_REQUIREMENT_CATEGORIES:
            category = "other"
        cleaned.append({"category": category, "requirement": requirement})
    return cleaned


async def _load_tender_doc_for_format(
    db: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """加载属本项目的招标文件（格式要求读写共用前置校验）."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.project_id != project_id:
        raise BizError(code=4004, message="文档不存在")
    if doc.doc_type != "tender_file":
        raise BizError(code=4010, message="仅招标文件支持格式要求")
    return doc


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

    # 事务约定（BUG-1）：登记 + 审计在入队前显式提交，
    # 确保 worker 领取解析/向量化任务时文档行已可见
    await db.commit()

    # 异步任务入队：解析/向量化由 worker 推进状态；Redis 不可用时降级不阻断上传
    if doc_type == "tender_file":
        await task_service.enqueue_parse_tender(project_id, doc.id)
    elif doc_type == "kb_material":
        await task_service.enqueue_index_document(project_id, doc.id)

    return success(data=DocumentUploadOut.model_validate(doc).model_dump(mode="json"))


@router.post("/{project_id}/images")
async def upload_image(
    project_id: uuid.UUID,
    file: UploadFile,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传章节插图（jpg/png/gif/webp ≤10MB），返回 storage_key 与签名 URL."""
    await _check_project_member(db, project_id, user_id)

    if file.content_type not in IMAGE_CONTENT_TYPES:
        raise ValidationError("仅支持 jpg/png/gif/webp 图片")

    content = await file.read()
    if len(content) > IMAGE_MAX_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"图片大小超过限制 ({IMAGE_MAX_SIZE_MB}MB)")

    storage_key = upload_file(
        io.BytesIO(content),
        filename=file.filename or "image.png",
        content_type=file.content_type or "application/octet-stream",
        key_prefix=f"images/{project_id}",
    )

    # 审计埋点：图片上传（security.md §4）
    await audit.record(
        db,
        user_id,
        "image.upload",
        project_id=project_id,
        target_type="image",
        target_id=storage_key,
        detail={"filename": file.filename, "size_bytes": len(content)},
    )

    # 事务约定（BUG-1）：审计响应前显式提交
    await db.commit()

    return success(
        data={"storage_key": storage_key, "url": presigned_url(storage_key)}
    )


@router.get("/{project_id}/images/signed")
async def get_image_signed_url(
    project_id: uuid.UUID,
    storage_key: str = Query(..., min_length=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """图片签名读：仅允许本项目 images 目录下的对象（防跨项目越权）."""
    await _check_project_member(db, project_id, user_id)
    if not storage_key.startswith(f"images/{project_id}/"):
        raise BizError(code=4003, message="无权访问该图片")
    return success(data={"url": presigned_url(storage_key)})


@router.post("/{project_id}/documents/{document_id}/reparse")
async def reparse_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重新解析招标文件：清除旧评分点 → 状态重置 → 重新入队（仅评分点提取）.

    适用场景：解析结果不理想（评分点缺失/不准确）时重新提取。
    只负责评分点提取，不做技术需求提取：招标原文技术需求保留，
    基于旧评分点的 sp_derived 衍生需求一并清除（重新梳理即可重建）。
    """
    await _check_project_member(db, project_id, user_id)

    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.project_id != project_id:
        raise BizError(code=4004, message="文档不存在")
    if doc.doc_type != "tender_file":
        raise BizError(code=4010, message="仅招标文件支持重新解析")
    if doc.status == "parsing":
        raise BizError(code=4010, message="文档正在解析中，请稍后重试")
    if doc.status == "uploaded":
        raise BizError(code=4010, message="解析任务已排队，请等待完成")

    # 清除该文档的旧评分点（按 doc_id，不影响同项目其他文档）；
    # 招标原文技术需求保留（重新解析只做评分点提取）；
    # 衍生技术需求（sp_derived）基于旧评分点梳理，一并清除
    await db.execute(delete(ScorePoint).where(ScorePoint.doc_id == document_id))
    await db.execute(
        delete(TechRequirement).where(
            TechRequirement.project_id == project_id,
            TechRequirement.source == "sp_derived",
        )
    )
    doc.status = "uploaded"
    await db.flush()

    # 审计埋点：重新解析（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.reparse",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
        detail={"title": doc.title},
    )

    # 事务约定（BUG-1）：状态重置 + 清理在入队前显式提交，
    # 确保 worker 领取任务时旧结果已删除、文档行已可见
    await db.commit()

    await task_service.enqueue_parse_tender(project_id, doc.id, score_points_only=True)

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


@router.get("/{project_id}/documents/{document_id}/format-requirements")
async def get_format_requirements(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读取招标文件格式要求汇总（项目成员可读）."""
    await _check_project_member(db, project_id, user_id)
    doc = await _load_tender_doc_for_format(db, project_id, document_id)
    items = doc.meta.get("format_requirements", []) if doc.meta else []
    return success(data={"items": items})


@router.put("/{project_id}/documents/{document_id}/format-requirements")
async def update_format_requirements(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: FormatRequirementsBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工编辑格式要求：清洗后幂等覆盖 meta.format_requirements."""
    await _check_project_member(db, project_id, user_id)
    doc = await _load_tender_doc_for_format(db, project_id, document_id)

    items = _clean_format_requirements(body.format_requirements)
    # 整体替换新 dict 确保 JSON 列标记脏（原地改 key 不触发变更检测）
    doc.meta = {**(doc.meta or {}), "format_requirements": items}
    await db.flush()

    # 审计埋点：格式要求人工修改（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.format_requirements_update",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
        detail={"count": len(items)},
    )

    # 事务约定（BUG-1）：写入 + 审计响应前显式提交
    await db.commit()
    return success(data={"items": items})


@router.get("/{project_id}/kb/search")
async def search_kb(
    project_id: uuid.UUID,
    q: str = Query(..., min_length=1, description="检索查询文本"),
    top_k: int = Query(5, ge=1, le=20, description="返回条数上限"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """资料库相似度检索（RAG，E2E-03 检索命中）.

    委托 rag_service.search_materials（embed → pgvector 余弦检索 → 补文档标题）。
    min_score 默认 0：按相似度倒序返回 top_k 条（LLM mock 模式下确定性伪向量
    相似度趋近 0，若设高阈值将恒无命中）。
    """
    await _check_project_member(db, project_id, user_id)

    items = await rag_service.search_materials(db=db, project_id=project_id, query=q, top_k=top_k)
    return success(data={"items": items, "total": len(items)})


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

    # 事务约定（BUG-1）：确认/策略修改响应前显式提交，后续工作流立即可见
    await db.commit()

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
