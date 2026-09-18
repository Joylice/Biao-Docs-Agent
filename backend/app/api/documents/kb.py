"""资料库检索路由 — RAG 相似度检索（第一轮-2 拆包自 api/documents.py）."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.services.llm import rag_service
from app.services.project.project_service import _check_project_member

router = APIRouter()


@router.get("/{project_id}/kb/search")
async def search_kb(
    project_id: uuid.UUID,
    q: str = Query(..., min_length=1, description="检索查询文本"),
    top_k: int = Query(5, ge=1, le=20, description="返回条数上限"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """资料库相似度检索（RAG，E2E-03 检索命中）.

    委托 rag_service.search_materials（embed → pgvector 余弦检索 → 补文档标题）。
    min_score 默认 0：按相似度倒序返回 top_k 条（LLM mock 模式下确定性伪向量
    相似度趋近 0，若设高阈值将恒无命中）。
    """
    await _check_project_member(db, project_id, user_id)

    items = await rag_service.search_materials(db=db, project_id=project_id, query=q, top_k=top_k)
    return success(data={"items": items, "total": len(items)})


__all__ = ["router"]
