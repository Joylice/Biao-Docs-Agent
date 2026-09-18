"""文档/图片存储路由 — 上传下载/列表/删除/重新解析（第一轮-2 拆包自 api/documents.py）.

本模块保留 MinIO 存储编排与 worker 任务入队（与 kb 模式一致）；
DB 操作委托 document_service，事务按 BUG-1 约定在响应/入队前显式 commit。
"""

import io
import mimetypes
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import BizError, ValidationError
from app.core.response import paginated, success
from app.schemas.document import DocumentListOut, DocumentUploadOut
from app.services.document import document_service
from app.services.document.storage_service import download_file, presigned_url, upload_file
from app.services.project import task_service
from app.services.project.project_service import _check_project_member

router = APIRouter()

# 章节插图：支持格式与大小上限（存 MinIO images/{project_id}/ 目录）
IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
IMAGE_MAX_SIZE_MB = 10


@router.post("/{project_id}/documents")
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile,
    doc_type: str = Query(..., description="tender_file|kb_material"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
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
    doc = await document_service.register_document(
        db, project_id, doc_type, file.filename or "unknown", storage_key, user_id
    )

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
) -> dict[str, Any]:
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

    return success(data={"storage_key": storage_key, "url": presigned_url(storage_key)})


@router.get("/{project_id}/images/signed")
async def get_image_signed_url(
    project_id: uuid.UUID,
    storage_key: str = Query(..., min_length=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """图片签名读：仅允许本项目 images 目录下的对象（防跨项目越权）."""
    await _check_project_member(db, project_id, user_id)
    if not storage_key.startswith(f"images/{project_id}/"):
        raise BizError(code=4003, message="无权访问该图片")
    return success(data={"url": presigned_url(storage_key)})


@router.get("/{project_id}/images/view")
async def view_image(
    project_id: uuid.UUID,
    key: str = Query(..., min_length=1),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """图片代理展示（阶段 2）：后端代理字节流，浏览器无需直连 MinIO 内网.

    供 Markdown 正文 <img> 渲染（前端 axios 拦截器自动带 JWT）。
    """
    await _check_project_member(db, project_id, user_id)
    if not key.startswith(f"images/{project_id}/"):
        raise BizError(code=4003, message="无权访问该图片")
    data = download_file(key)
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{project_id}/documents/{document_id}/download")
async def download_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """文档下载代理（阶段 2）：流式字节 + Content-Disposition，成员校验 + 审计."""
    await _check_project_member(db, project_id, user_id)
    doc = await document_service.get_document(db, project_id, document_id)

    data = download_file(doc.storage_key)

    # 审计埋点：文档下载（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.download",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
    )
    await db.commit()

    filename = doc.title or document_id.hex
    encoded = quote(filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )


@router.post("/{project_id}/documents/{document_id}/reparse")
async def reparse_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """重新解析招标文件：清除旧评分点 → 状态重置 → 重新入队（仅评分点提取）.

    适用场景：解析结果不理想（评分点缺失/不准确）时重新提取。
    """
    await _check_project_member(db, project_id, user_id)

    doc = await document_service.prepare_reparse(db, project_id, document_id)

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
) -> dict[str, Any]:
    """文档列表."""
    await _check_project_member(db, project_id, user_id)

    items, total = await document_service.list_documents(db, project_id, doc_type, page, page_size)
    items_data = [DocumentListOut.model_validate(d).model_dump(mode="json") for d in items]
    return paginated(items_data, total)


@router.delete("/{project_id}/documents/{document_id}")
async def delete_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除文档及其关联的评分点/技术需求/废标条款（清理重复/失败文件）."""
    await _check_project_member(db, project_id, user_id)

    doc = await document_service.delete_document(db, project_id, document_id)

    # 审计埋点：文档删除（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.delete",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
        detail={"title": doc.title, "doc_type": doc.doc_type},
    )

    # 事务约定（BUG-1）：删除 + 审计响应前显式提交
    await db.commit()
    return success(data={"id": str(doc.id), "title": doc.title})


__all__ = ["router"]
