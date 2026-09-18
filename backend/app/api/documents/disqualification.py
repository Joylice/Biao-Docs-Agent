"""废标条款路由 — 文档级读取/编辑 + 项目级汇总/风险扫描（第一轮-2 拆包自 api/documents.py）.

清洗逻辑已下沉 dq_service.clean_clause_payloads（第一轮-2 路由薄化）。
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
from app.services.proposal import disqualification_service as dq_service  # 废标条款服务（阶段 H）

from .core import DisqualificationClausesBody

router = APIRouter()


@router.get("/{project_id}/documents/{document_id}/disqualification-clauses")
async def get_disqualification_clauses(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取招标文件的废标/红线条款列表（项目成员可读，阶段 H）."""
    await _check_project_member(db, project_id, user_id)
    await document_service.load_tender_doc_for_format(db, project_id, document_id)
    clauses = await document_service.list_doc_clauses(db, project_id, document_id)
    items = [document_service.clause_to_dict(c) for c in clauses]
    return success(data={"items": items})


@router.put("/{project_id}/documents/{document_id}/disqualification-clauses")
async def update_disqualification_clauses(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DisqualificationClausesBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """人工编辑废标条款：清洗后删旧插新幂等覆盖（阶段 H）."""
    await _check_project_member(db, project_id, user_id)
    doc = await document_service.load_tender_doc_for_format(db, project_id, document_id)

    cleaned = dq_service.clean_clause_payloads(body.items)

    await document_service.replace_doc_clauses(db, project_id, doc.id, cleaned)

    # 审计埋点：废标条款人工修改（security.md §4）
    await audit.record(
        db,
        user_id,
        "document.disqualification_clauses_update",
        project_id=project_id,
        target_type="document",
        target_id=str(doc.id),
        detail={"count": len(cleaned)},
    )

    await db.commit()
    return success(data={"items": [{"id": "", **item} for item in cleaned]})


@router.get("/{project_id}/disqualification-clauses")
async def list_project_disqualification_clauses(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """项目级废标条款汇总（跨文档，供生成页风险横幅）."""
    await _check_project_member(db, project_id, user_id)
    clauses = await dq_service.load_project_clauses(db, project_id)
    return success(data={"items": [document_service.clause_to_dict(c) for c in clauses]})


@router.get("/{project_id}/disqualification-risks")
async def list_disqualification_risks(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """章节废标风险扫描：{章节号: 命中条款清单}（供审阅页警告条）."""
    await _check_project_member(db, project_id, user_id)
    risks = await dq_service.scan_project_sections(db, project_id)
    return success(data={"risks": risks})


__all__ = ["router"]
