"""术语表只读 API 路由 — 查询招标文件 meta.glossary.

术语表在解析阶段由 LLM 写入 Document.meta["glossary"]，本路由只读返回。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.services.document import document_service
from app.services.project.project_service import _check_project_member

router = APIRouter()


@router.get("/{project_id}/documents/{document_id}/glossary")
async def get_doc_glossary(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取文档术语表（只读，存 doc.meta.glossary）.

    术语表格式：[{term, canonical, desc}]
    """
    await _check_project_member(db, project_id, user_id)

    doc = await document_service.get_document(db, project_id, document_id)
    items = (doc.meta or {}).get("glossary", [])
    return success(data={"items": items})


__all__ = ["router"]
