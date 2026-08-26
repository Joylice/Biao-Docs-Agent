"""上下文刷新节点 — regenerate 路径从 DB 刷新源数据写回 state（单一数据源）.

regenerate 时 checkpointer 中的 state 可能含旧数据（未确认评分点/资格需求），
本节点独立负责从 DB 重新读取最新源数据并写回 state，generate_outline 改纯 state 读。
"""

import hashlib
import json
import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import _is_qualification_req, logger
from app.models.project import Project


async def refresh_context_node(state: dict) -> dict:
    """节点：刷新上下文 — 从 DB 重新读取最新源数据写回 state（regenerate 路径）.

    只读块无需 commit（对齐 _shared.py 事务约定）；失败返回 {} 保持 state 不变
    （不阻塞 regenerate）。
    glossary 不纳入指纹（非关键上下文，保持简单）。
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return {}
    try:
        async with _pkg.async_session_factory() as db:
            project_name, tender_no, sps, trs, glossary = await _pkg._load_tender_context(
                db, project_id
            )
            # 补查 industry（_load_tender_context 不含，不改其签名避免牵动 parse/测试）
            result = await db.execute(
                select(Project).where(Project.id == uuid.UUID(project_id))
            )
            project = result.scalar_one_or_none()
            industry = (project.industry or "") if project else ""

        # 排除资格/商务类技术需求（与 2026-08-25 大纲修复一致）
        trs = [tr for tr in trs if not _is_qualification_req(tr.get("description", ""))]

        # 血缘指纹：ScorePoint/TechRequirement 无 updated_at 列，用内容指纹；数据未变时稳定
        context_version = hashlib.sha256(
            json.dumps(
                {"sps": sps, "trs": trs, "pn": project_name, "tn": tender_no},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:16]

        return {
            "score_points": sps,
            "tech_requirements": trs,
            "project_name": project_name,
            "tender_no": tender_no,
            "industry": industry,
            "glossary": glossary,
            "context_version": context_version,
        }
    except Exception:
        logger.warning("刷新上下文失败，保留 state 原值")
        return {}
