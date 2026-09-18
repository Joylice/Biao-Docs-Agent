"""招标解析节点 — parse_tender（读已确认解析结果）+ confirm_score_points（HITL）."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.agents.state import BidState
from app.models.document import Document, ScorePoint
from app.models.project import Project


async def _load_tender_context(
    db: AsyncSession, project_id: str
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    """读取项目名称/编号 + 已解析的评分点与术语表（阶段 E2）.

    P3：技术需求已移除，不再从 DB 查询 TechRequirement。
    """
    proj_result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = proj_result.scalar_one_or_none()
    project_name = project.name if project else ""
    tender_no = project.tender_no or "" if project else ""

    sp_result = await db.execute(
        select(ScorePoint)
        .where(
            ScorePoint.project_id == uuid.UUID(project_id),
            # 2026-08-25 严格模式：仅已确认评分点进入大纲生成
            ScorePoint.confirmed.is_(True),
        )
        .order_by(ScorePoint.clause_no)
    )
    score_points = [
        {
            "id": str(sp.id),
            "clause_no": sp.clause_no,
            "item": sp.item,
            "score": float(sp.score) if sp.score is not None else None,
            "criteria": sp.criteria,
            "is_star": sp.is_star,
            "strategy": sp.strategy,
            "risk_level": sp.risk_level,
            "confirmed": sp.confirmed,
        }
        for sp in sp_result.scalars().all()
    ]

    # 术语表：解析阶段写入招标文件 meta.glossary（阶段 E2）
    doc_result = await db.execute(
        select(Document).where(
            Document.project_id == uuid.UUID(project_id),
            Document.doc_type == "tender_file",
        )
    )
    tender_doc = doc_result.scalar_one_or_none()
    glossary = (tender_doc.meta or {}).get("glossary", []) if tender_doc else []
    return project_name, tender_no, score_points, glossary


async def parse_tender_node(state: BidState) -> dict[str, Any]:
    """节点：招标解析 — 从 DB 读取已确认解析结果（不重复调 LLM）."""
    project_id = state.get("project_id", "")
    if not project_id:
        return {"error": "缺少 project_id", "current_phase": "init"}

    try:
        async with _pkg.async_session_factory() as db:
            (
                project_name,
                tender_no,
                score_points,
                glossary,
            ) = await _pkg._load_tender_context(db, project_id)
            # 补读 industry（正常启动路径与 regenerate 路径上下文一致）
            proj_result = await db.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = proj_result.scalar_one_or_none()
            industry = (project.industry or "") if project else ""
            if not score_points:
                return {
                    "error": "项目尚未完成招标解析（无评分点），请先解析招标文件",
                    "current_phase": "init",
                }
            await _pkg._update_workflow(
                db, project_id, phase="confirm", progress=0.15, status="waiting"
            )
            await db.commit()  # BUG-2：workflow 元数据写入显式提交
        return {
            "score_points": score_points,
            "glossary": glossary,
            "project_name": project_name,
            "tender_no": tender_no,
            "industry": industry,
            "current_phase": "confirm",
            "progress": 0.15,
        }
    except Exception as e:
        logger.exception("读取解析结果失败")
        return {"error": f"读取解析结果失败: {e}", "current_phase": "init"}


async def confirm_score_points_node(state: BidState) -> dict[str, Any]:
    """节点：HITL — 等待人工确认评分点."""
    from langgraph.types import interrupt

    decision = interrupt(
        {
            "type": "confirm_score_points",
            "score_points": state.get("score_points", []),
            "message": "请确认评分点提取结果",
        }
    )
    confirmed = decision is True or (
        isinstance(decision, dict) and decision.get("confirmed") is True
    )
    if not confirmed:
        return {"error": "评分点未确认", "current_phase": "confirm"}
    return {"current_phase": "outline", "progress": 0.25}
