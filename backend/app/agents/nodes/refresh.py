"""上下文刷新节点 — regenerate 路径从 DB 刷新源数据写回 state（单一数据源）.

P3：技术需求已移除，不再查询/注入，指纹改为 {sps, pn, tn}（见 decisions/0002）。
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.agents.state import BidState
from app.models.project import Project


async def refresh_context_node(state: BidState) -> dict[str, Any]:
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
            project_name, tender_no, sps, glossary = await _pkg._load_tender_context(db, project_id)
            # 补查 industry（_load_tender_context 不含，不改其签名避免牵动 parse/测试）
            result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
            project = result.scalar_one_or_none()
            industry = (project.industry or "") if project else ""

        # 血缘指纹：ScorePoint 无 updated_at 列，用内容指纹；数据未变时稳定
        context_version = hashlib.sha256(
            json.dumps(
                {"sps": sps, "pn": project_name, "tn": tender_no},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:16]

        return {
            "score_points": sps,
            "project_name": project_name,
            "tender_no": tender_no,
            "industry": industry,
            "glossary": glossary,
            "context_version": context_version,
        }
    except Exception:
        logger.warning("刷新上下文失败，保留 state 原值")
        return {}
