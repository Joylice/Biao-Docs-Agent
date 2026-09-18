"""格式要求路由 — 招标文件格式要求读取/人工编辑（第一轮-2 拆包自 api/documents.py）.

清洗逻辑已下沉 document_service.clean_format_requirements（第一轮-2 路由薄化）。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.response import success
from app.services.document import document_service
from app.services.project.project_service import _check_project_member

from .core import FormatRequirementsBody

router = APIRouter()


@router.get("/{project_id}/documents/{document_id}/format-requirements")
async def get_format_requirements(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取招标文件格式要求汇总（项目成员可读）."""
    await _check_project_member(db, project_id, user_id)
    doc = await document_service.load_tender_doc_for_format(db, project_id, document_id)
    items = doc.meta.get("format_requirements", []) if doc.meta else []
    return success(data={"items": items})


@router.put("/{project_id}/documents/{document_id}/format-requirements")
async def update_format_requirements(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: FormatRequirementsBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """人工编辑格式要求：清洗后幂等覆盖 meta.format_requirements."""
    await _check_project_member(db, project_id, user_id)

    items = document_service.clean_format_requirements(body.format_requirements)
    doc = await document_service.save_format_requirements(db, project_id, document_id, items)

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


@router.get("/{project_id}/documents/{document_id}/parse-warnings")
async def get_parse_warnings(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取解析交叉校验告警（P2 — validator Agent 产出，存 doc.meta）.

    随既有查询返回，不新增 WS/事件通道。
    失败降级「交叉校验未完成」不阻断（返回空列表 + status 字段）。
    """
    await _check_project_member(db, project_id, user_id)
    doc = await document_service.load_tender_doc_for_format(db, project_id, document_id)
    warnings = (doc.meta or {}).get("parse_warnings", [])
    return success(data={"items": warnings, "count": len(warnings)})


__all__ = ["router"]
