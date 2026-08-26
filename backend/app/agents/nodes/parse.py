"""招标解析节点 — parse_tender（读已确认解析结果）+ confirm_score_points（HITL）."""

import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.models.document import Document, ScorePoint, TechRequirement
from app.models.project import Project


async def _load_tender_context(
    db, project_id: str
) -> tuple[str, str, list[dict], list[dict], list[dict]]:
    """读取项目名称/编号 + 已解析的评分点、技术需求与术语表（阶段 E2）."""
    proj_result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = proj_result.scalar_one_or_none()
    project_name = project.name if project else ""
    tender_no = project.tender_no or "" if project else ""

    sp_result = await db.execute(
        select(ScorePoint)
        .where(
            ScorePoint.project_id == uuid.UUID(project_id),
            # 2026-08-25 严格模式：仅已确认评分点进入大纲生成（与技术需求梳理对齐）
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

    tr_result = await db.execute(
        select(TechRequirement)
        .where(TechRequirement.project_id == uuid.UUID(project_id))
        .order_by(TechRequirement.seq)
    )
    tech_requirements = [
        {
            "id": str(tr.id),
            "seq": tr.seq,
            "description": tr.description,
            "category": tr.category,
            "is_mandatory": tr.is_mandatory,
            # 评分点→技术需求关联（2026-08-25 评分点核心纲要所需）：
            # sp_id 归属评分点，source 来源（sp_derived=由评分点梳理衍生 / tender=招标原文提取）
            "sp_id": str(tr.sp_id) if tr.sp_id else None,
            "source": tr.source,
        }
        for tr in tr_result.scalars().all()
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
    return project_name, tender_no, score_points, tech_requirements, glossary


async def parse_tender_node(state: dict) -> dict:
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
                tech_requirements,
                glossary,
            ) = await _pkg._load_tender_context(db, project_id)
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
            "tech_requirements": tech_requirements,
            "glossary": glossary,
            "project_name": project_name,
            "tender_no": tender_no,
            "current_phase": "confirm",
            "progress": 0.15,
        }
    except Exception as e:
        logger.exception("读取解析结果失败")
        return {"error": f"读取解析结果失败: {e}", "current_phase": "init"}


async def confirm_score_points_node(state: dict) -> dict:
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
