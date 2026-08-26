"""评分对标服务 — 阶段 D（SDD §3.4）.

对标表字段：clause_no / item / score / criteria / strategy / coverage / risk_level。
风险分级：risk = f(score, coverage) —— 分值高且资料库无对应素材 → high（提示售前补资料）；
输出按 score × (1 - coverage) 降序，供前端排序展示。GET benchmark 懒计算并回写 risk_level。
"""

import hashlib
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models.document import ScorePoint
from app.services.infra import settings_service

logger = logging.getLogger(__name__)

# coverage 检索配置（阈值常量便于调优）
COVERAGE_TOP_K = 5

# 风险分级阈值：score ≥ HIGH_SCORE 且 coverage < HIGH_COVERAGE_MAX → high
HIGH_SCORE_THRESHOLD = 6.0
HIGH_COVERAGE_MAX = 0.3
# score ≥ MID_SCORE 或 coverage < MID_COVERAGE_MAX → mid，否则 low
MID_SCORE_THRESHOLD = 3.0
MID_COVERAGE_MAX = 0.6

# mock 模式无高风险记录时的确定性注入样本（1.4 提示词回归验证用）
MOCK_HIGH_RISK_SAMPLE: list[dict] = [
    {
        "clause_no": "MOCK-HR",
        "strategy": "mock 对标注入样本：本章须明确响应该高风险评分点的判定标准",
    },
]


def risk_level(score: float, coverage: float) -> str:
    """风险分级：high = 高分且资料库素材缺口大；mid/low 见阈值常量."""
    if score >= HIGH_SCORE_THRESHOLD and coverage < HIGH_COVERAGE_MAX:
        return "high"
    if score >= MID_SCORE_THRESHOLD or coverage < MID_COVERAGE_MAX:
        return "mid"
    return "low"


async def _retrieve(db: AsyncSession, project_id: uuid.UUID, query: str):
    """资料库检索（向量召回 + rerank 精排；独立函数便于测试桩替）."""
    from app.services.llm.rag_service import get_embedding, retrieve_with_rerank

    query_embedding = await get_embedding(query)
    return await retrieve_with_rerank(
        db=db,
        project_id=project_id,
        query=query,
        query_embedding=query_embedding,
        top_k=COVERAGE_TOP_K,
    )


async def compute_item_coverage(db: AsyncSession, project_id: uuid.UUID, sp: ScorePoint) -> float:
    """评分点素材覆盖度 ∈ [0,1]：item+criteria 检索命中数 / top_k.

    mock 模式走确定性规则（sha256(query) → [0,1]），保证测试与演示可复现；
    检索失败降级 0.0（按无素材处理，风险分级偏保守）。
    """
    query = f"{sp.item or ''} {sp.criteria or ''}".strip()
    if not query:
        return 0.0
    if await settings_service.is_mock_enabled():
        digest = hashlib.sha256(query.encode("utf-8")).digest()
        return (digest[0] % 11) / 10
    try:
        results = await _retrieve(db, project_id, query)
        return len(results) / COVERAGE_TOP_K
    except Exception as e:
        logger.warning("对标 coverage 检索失败（降级 0.0）: %s", e)
        return 0.0


async def build_benchmark(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    """confirmed 评分点 → 懒计算 coverage/risk 并回写 risk_level，按 score × (1 - coverage) 降序."""
    result = await db.execute(
        select(ScorePoint).where(
            ScorePoint.project_id == project_id,
            ScorePoint.confirmed.is_(True),
        )
    )
    items: list[dict] = []
    for sp in result.scalars().all():
        coverage = await compute_item_coverage(db, project_id, sp)
        level = risk_level(float(sp.score or 0), coverage)
        sp.risk_level = level  # 懒回写（端点侧 commit）
        items.append(
            {
                "clause_no": sp.clause_no,
                "item": sp.item,
                "score": float(sp.score or 0),
                "criteria": sp.criteria or "",
                "strategy": sp.strategy or "",
                "coverage": round(coverage, 2),
                "risk": level,
            }
        )
    items.sort(key=lambda x: x["score"] * (1 - x["coverage"]), reverse=True)
    return items


async def update_strategy(
    db: AsyncSession, project_id: uuid.UUID, clause_no: str, strategy: str
) -> ScorePoint:
    """编辑评分点应对策略（strip 后为空置 None）；评分点不存在抛 BizError 4004.

    审计留痕与 commit 由 api 层执行（事务约定 BUG-1）。
    """
    result = await db.execute(
        select(ScorePoint).where(
            ScorePoint.project_id == project_id,
            ScorePoint.clause_no == clause_no,
        )
    )
    sp = result.scalar_one_or_none()
    if sp is None:
        raise BizError(code=4004, message=f"评分点 {clause_no} 不存在")
    sp.strategy = strategy.strip() or None
    return sp


async def load_high_risk_points(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    """write_node 注入用高风险评分点（1.4）：strategy 缺失回退 item.

    mock 模式无高风险记录时注入确定性样本，保证提示词回归可验证。
    """
    result = await db.execute(
        select(ScorePoint).where(
            ScorePoint.project_id == project_id,
            ScorePoint.confirmed.is_(True),
            ScorePoint.risk_level == "high",
        )
    )
    points = [
        {"clause_no": sp.clause_no, "strategy": sp.strategy or sp.item}
        for sp in result.scalars().all()
    ]
    if not points and await settings_service.is_mock_enabled():
        return list(MOCK_HIGH_RISK_SAMPLE)
    return points
