"""文档管理服务 — 文档登记/归属校验/列表/重新解析重置/格式要求/评分点/技术需求/废标条款.

分层约定（批次 1c）：api 层不直接执行 SQL，DB 操作统一下沉于此；
MinIO 存储与 worker 任务入队编排仍留 api 层（与 kb 模式一致）。
事务约定：仅 flush 不 commit，提交由 api 层显式执行（BUG-1）。
"""

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models.document import DisqualificationClause, Document, ScorePoint

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


def clean_format_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清洗格式要求条目：丢弃空 requirement，未知 category 归入 other.

    自 api/documents 下沉（第一轮-2 路由薄化），行为与原路由层实现一致。
    """
    cleaned: list[dict[str, Any]] = []
    for item in items:
        requirement = str(item.get("requirement") or "").strip()
        if not requirement:
            continue
        category = str(item.get("category") or "").strip()
        if category not in FORMAT_REQUIREMENT_CATEGORIES:
            category = "other"
        cleaned.append({"category": category, "requirement": requirement})
    return cleaned


def clause_to_dict(c: DisqualificationClause) -> dict[str, Any]:
    """废标条款序列化（与前端废标风险卡片字段对齐）."""
    return {
        "id": str(c.id),
        "clause_no": c.clause_no,
        "title": c.title,
        "risk_category": c.risk_category,
        "severity": c.severity,
        "recommendation": c.recommendation,
        "confirmed": c.confirmed,
    }


async def get_document(db: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """按 id 载入属本项目的文档；不存在或跨项目 → 4004（防越权）."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or doc.project_id != project_id:
        raise BizError(code=4004, message="文档不存在")
    return doc


async def load_tender_doc_for_format(
    db: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """加载属本项目的招标文件（格式要求/废标条款读写共用前置校验）."""
    doc = await get_document(db, project_id, document_id)
    if doc.doc_type != "tender_file":
        raise BizError(code=4010, message="仅招标文件支持格式要求")
    return doc


async def register_document(
    db: AsyncSession,
    project_id: uuid.UUID,
    doc_type: str,
    title: str,
    storage_key: str,
    created_by: uuid.UUID,
) -> Document:
    """登记文档记录（status=uploaded）；flush + refresh，不 commit."""
    doc = Document(
        project_id=project_id,
        doc_type=doc_type,
        title=title,
        storage_key=storage_key,
        status="uploaded",
        created_by=created_by,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def list_documents(
    db: AsyncSession,
    project_id: uuid.UUID,
    doc_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    """文档列表（可选 doc_type 过滤；created_at 倒序分页）."""
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
    return list(result.scalars().all()), total


async def prepare_reparse(
    db: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """重新解析前置：校验 → 清除该文档旧评分点 → 状态重置 uploaded（仅 flush）.

    只清除评分点。**废标/红线条款的幂等清理不在此处**，由 `worker.tasks.task_parse_tender`
    在写库前统一完成（同时覆盖首次解析与并发 reparse，见
    `tests/unit/test_worker_tasks.py::TestTaskParseTenderIdempotentCleanup`）。
    两处都在「保存新结果前清旧」，但职责不同：本函数保证 reparse 请求被接受后
    评分点即刻置空（前端不再展示上一轮结果），worker 保证写库原子幂等。

    P3（见 docs/decisions/0002）已移除技术需求及其衍生概念，故不再有项目级
    衍生需求清理；此处仅清除本文件解析产出的评分点。
    """
    doc = await get_document(db, project_id, document_id)
    if doc.doc_type != "tender_file":
        raise BizError(code=4010, message="仅招标文件支持重新解析")
    if doc.status == "parsing":
        raise BizError(code=4010, message="文档正在解析中，请稍后重试")
    if doc.status == "uploaded":
        raise BizError(code=4010, message="解析任务已排队，请等待完成")

    # 清除该文档的旧评分点（按 doc_id，不影响同项目其他文档）
    await db.execute(delete(ScorePoint).where(ScorePoint.doc_id == document_id))
    doc.status = "uploaded"
    await db.flush()
    return doc


async def save_format_requirements(
    db: AsyncSession,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> Document:
    """人工编辑格式要求：清洗后条目幂等覆盖 meta.format_requirements（仅 flush）."""
    doc = await load_tender_doc_for_format(db, project_id, document_id)
    # 整体替换新 dict 确保 JSON 列标记脏（原地改 key 不触发变更检测）
    doc.meta = {**(doc.meta or {}), "format_requirements": items}
    await db.flush()
    return doc


async def list_score_points(db: AsyncSession, project_id: uuid.UUID) -> list[ScorePoint]:
    """评分点列表（clause_no 正序）."""
    result = await db.execute(
        select(ScorePoint).where(ScorePoint.project_id == project_id).order_by(ScorePoint.clause_no)
    )
    return list(result.scalars().all())


async def update_score_point(
    db: AsyncSession,
    project_id: uuid.UUID,
    sp_id: uuid.UUID,
    strategy: str | None,
    confirmed: bool | None,
) -> ScorePoint:
    """更新评分点（人工编辑 strategy 或确认）；不存在 → 4004（仅 flush + refresh）."""
    result = await db.execute(
        select(ScorePoint).where(ScorePoint.id == sp_id, ScorePoint.project_id == project_id)
    )
    sp = result.scalar_one_or_none()
    if not sp:
        raise BizError(code=4004, message="评分点不存在")

    if strategy is not None:
        sp.strategy = strategy
    if confirmed is not None:
        sp.confirmed = confirmed

    await db.flush()
    await db.refresh(sp)
    return sp


async def list_doc_clauses(
    db: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID
) -> list[DisqualificationClause]:
    """文档级废标/红线条款列表（clause_no 正序，阶段 H）."""
    result = await db.execute(
        select(DisqualificationClause)
        .where(
            DisqualificationClause.project_id == project_id,
            DisqualificationClause.doc_id == document_id,
        )
        .order_by(DisqualificationClause.clause_no)
    )
    return list(result.scalars().all())


async def replace_doc_clauses(
    db: AsyncSession,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> None:
    """人工编辑废标条款：删旧插新幂等覆盖（仅 flush，阶段 H）."""
    await db.execute(
        delete(DisqualificationClause).where(
            DisqualificationClause.project_id == project_id,
            DisqualificationClause.doc_id == document_id,
        )
    )
    for item in items:
        db.add(DisqualificationClause(project_id=project_id, doc_id=document_id, **item))
    await db.flush()


async def delete_document(
    db: AsyncSession,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document:
    """删除文档及其关联的评分点/技术需求/废标条款（仅 flush，不删 MinIO 文件）.

    适用场景：清理重复上传/解析失败的招标文件。MinIO 文件保留（避免误删
    其他文档引用的对象），由后台定期清理孤儿对象。
    """
    doc = await get_document(db, project_id, document_id)
    # 级联删除关联数据
    await db.execute(delete(ScorePoint).where(ScorePoint.doc_id == document_id))
    await db.execute(
        delete(DisqualificationClause).where(DisqualificationClause.doc_id == document_id)
    )
    await db.delete(doc)
    await db.flush()
    return doc
