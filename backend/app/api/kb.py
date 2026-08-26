"""全局资料库 API 路由 — 资料库独立管理（不绑定项目，方案生成时挂载选用）.

设计：kb_material 文档 project_id IS NULL = 全局共享资料；上传/列表/检索不依赖
项目；方案生成通过 confirm-outline 的 mounted_doc_ids 挂载（见 api/workflow.py）。

权限（三期决策）：上传/列表/检索登录可用；删除限资料库管理员（get_current_kb_admin_id，
role ∈ {kb_admin, admin}，白名单兼容并存）。

DB 操作委托 kb_base_service / kb_material_service（批次 1b 分层重构）；
本层保留路由/参数校验/MinIO 与入队编排/审计/显式 commit/响应组装。
"""

import contextlib
import io
import mimetypes
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_kb_admin_id, get_current_user_id
from app.core.exceptions import ValidationError
from app.core.response import paginated, success
from app.schemas.document import (
    DocumentListOut,
    DocumentUploadOut,
    MaterialUpdateIn,
    validate_category,
    validate_tags,
)

# 分组导入（R1 重构）：infra/kb_base_service、llm/rag_service 等
from app.services.document import storage_service
from app.services.infra import kb_base_service, kb_material_service
from app.services.llm import rag_service
from app.services.project import task_service

router = APIRouter()


@router.post("/materials")
async def upload_material(
    file: UploadFile,
    category: str | None = Form(None, description="素材分类（三期 S2，可选）"),
    tags: str = Form("", description="标签，逗号分隔（三期 S2，可选）"),
    kb_id: uuid.UUID | None = Form(None, description="归属知识库（2026-08-18，可选）"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传全局资料库素材（pdf/doc/docx/jpg/png；可选归入指定知识库）."""
    # 校验文件类型与大小
    if file.content_type not in settings.allowed_upload_types:
        raise ValidationError(f"不支持的文件类型: {file.content_type}")

    # 知识库归属校验（库存在且当前用户有写权限）
    target_kb = None
    if kb_id is not None:
        target_kb = await kb_base_service.get_base_for_upload(db, kb_id, user_id)

    # 三期 S2：分类/标签校验（枚举 + 上限）
    try:
        doc_category = validate_category(category)
        doc_tags = validate_tags([t for t in tags.split(",") if t.strip()] if tags else [])
    except ValueError as e:
        raise ValidationError(str(e)) from None

    content = await file.read()
    max_size = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise ValidationError(f"文件大小超过限制 ({settings.max_upload_size_mb}MB)")

    # 上传到 MinIO（project_id=None → global 前缀）
    storage_key = storage_service.upload_file(
        io.BytesIO(content),
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        project_id=None,
    )

    # 登记文档（project_id IS NULL = 全局资料；kb_id 归属知识库）
    doc = await kb_material_service.register_material(
        db,
        title=file.filename or "unknown",
        storage_key=storage_key,
        category=doc_category,
        tags=doc_tags,
        kb_id=target_kb.id if target_kb else None,
        user_id=user_id,
    )

    await audit.record(
        db,
        user_id,
        "kb.material_upload",
        target_type="document",
        target_id=str(doc.id),
        detail={"title": doc.title, "size_bytes": len(content)},
    )
    # 事务约定（BUG-1）：登记 + 审计先提交，worker 领取任务时文档行可见
    await db.commit()

    # 向量化任务入队（Redis 不可用降级不阻断）
    await task_service.enqueue_index_document(None, doc.id)

    return success(data=DocumentUploadOut.model_validate(doc).model_dump(mode="json"))


@router.get("/materials")
async def list_materials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, description="分类精确过滤（三期 S2）"),
    tag: str | None = Query(None, description="标签过滤：JSON 包含匹配（三期 S2）"),
    kb_id: uuid.UUID | None = Query(None, description="知识库过滤（2026-08-18）"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全局资料库列表（仅 kb_material，project_id IS NULL；按知识库可见性过滤）.

    可见性（2026-08-18）：kb_id IS NULL 存量未归档 / 公司库全员 / 本人个人库 /
    用户所属项目的项目库；他人个人库素材不可见。
    """
    rows, total = await kb_material_service.list_global_materials(
        db,
        user_id,
        page=page,
        page_size=page_size,
        category=category,
        tag=tag,
        kb_id=kb_id,
    )
    items = []
    for doc, uploader_name in rows:
        item = DocumentListOut.model_validate(doc).model_dump(mode="json")
        item["uploader_name"] = uploader_name or ""  # created_by 为空时展示空串
        items.append(item)

    return paginated(items, total)


@router.delete("/materials/{doc_id}")
async def delete_material(
    doc_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_kb_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除全局资料（仅资料库管理员；文件 + 文档记录 + 分块 CASCADE）."""
    doc = await kb_material_service.get_global_material(db, doc_id)

    # 删除 MinIO 文件（失败不阻断记录删除）
    with contextlib.suppress(Exception):
        storage_service.delete_file(doc.storage_key)

    await audit.record(
        db,
        user_id,
        "kb.material_delete",
        target_type="document",
        target_id=str(doc.id),
        detail={"title": doc.title},
    )
    await kb_material_service.delete_material(db, doc)
    await db.commit()
    return success(data={"id": str(doc_id)})


@router.patch("/materials/{doc_id}")
async def update_material(
    doc_id: uuid.UUID,
    req: MaterialUpdateIn,
    user_id: uuid.UUID = Depends(get_current_kb_admin_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑全局素材（仅资料库管理员；title/category/tags 均可选）."""
    doc, changed = await kb_material_service.update_material(
        db, doc_id, title=req.title, category=req.category, tags=req.tags
    )

    await audit.record(
        db,
        user_id,
        "kb.material_update",
        target_type="document",
        target_id=str(doc.id),
        detail={"changed": changed},
    )
    await db.commit()
    return success(data=DocumentListOut.model_validate(doc).model_dump(mode="json"))


@router.get("/materials/{doc_id}/download")
async def download_material(
    doc_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """素材下载代理（阶段 2）：登录即可下载全局素材；项目级文档不可经本接口（隔离）."""
    doc = await kb_material_service.get_material_for_download(db, doc_id)

    data = storage_service.download_file(doc.storage_key)

    # 审计埋点：素材下载（security.md §4）
    await audit.record(
        db,
        user_id,
        "kb.material_download",
        target_type="document",
        target_id=str(doc.id),
    )
    await db.commit()

    filename = doc.title or doc_id.hex
    encoded = quote(filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.get("/materials/search")
async def search_materials(
    q: str = Query(..., min_length=1, description="检索查询文本"),
    top_k: int = Query(5, ge=1, le=20),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全局资料库检索测试（RAG 命中验证）."""
    # 取全部全局资料的 doc_ids 作为检索范围
    doc_ids = await kb_material_service.global_material_doc_ids(db)

    items = await rag_service.search_materials(
        db=db,
        project_id=uuid.uuid4(),  # 占位：doc_ids 显式传入时忽略 project 过滤
        query=q,
        top_k=top_k,
        doc_ids=doc_ids,  # 恒传列表（空列表=无全局资料→无命中，不退化为占位 project 检索）
    )
    return success(data={"items": items, "total": len(items)})
