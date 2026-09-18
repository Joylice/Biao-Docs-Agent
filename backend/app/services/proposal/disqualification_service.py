"""废标条款服务 — 枚举归一 + 规则比对 + 项目扫描（阶段 H）.

规则比对为确定性启发式：已确认条款的「分类关键词 / 标题前缀」出现在章节正文
即判定该章节触碰红线（交由人工复核），不做语义级违规判定（真实模式可由
validate 工具复核链路补充）。
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.document import DisqualificationClause
from app.models.proposal import ProposalSection

# 风险分类枚举（与迁移 0017 / parse.yaml 提示词对齐）
RISK_CATEGORIES = frozenset(
    {
        "qualification_missing",  # 资质缺失
        "schedule_exceeded",  # 工期超限
        "signature_seal",  # 签章要求
        "blind_bid",  # 暗标规则
        "format_deviation",  # 格式偏离
        "substantive_deviation",  # 实质性偏离
        "other",
    }
)

SEVERITY_LEVELS = frozenset({"high", "mid", "low"})

# 分类 → 正文关键词（命中即视为章节触碰该红线领域）
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "qualification_missing": ("资质", "资格", "许可证", "认证", "证书"),
    "schedule_exceeded": ("工期", "日历天", "完工", "交付期", "竣工"),
    "signature_seal": ("签章", "盖章", "签字", "公章", "签署"),
    "blind_bid": ("暗标", "署名", "投标人名称", "标记"),
    "format_deviation": ("格式", "装订", "页码", "目录", "偏离"),
    "substantive_deviation": ("实质性", "偏离", "负偏离", "不满足"),
}


def normalize_severity(value: object) -> str:
    """severity 归一：小写合法值透传，非法/空值归 mid."""
    text = str(value or "").strip().lower()
    return text if text in SEVERITY_LEVELS else "mid"


def normalize_risk_category(value: object) -> str:
    """risk_category 归一：合法值透传，非法/空值归 other."""
    text = str(value or "").strip().lower()
    return text if text in RISK_CATEGORIES else "other"


def clean_clause_payloads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清洗废标条款载荷：缺 title 丢弃；枚举归一；默认值填充.

    自 api/documents 下沉（第一轮-2 路由薄化），行为与原路由层实现一致。
    """
    cleaned: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        cleaned.append(
            {
                "clause_no": str(item.get("clause_no") or "").strip() or "-",
                "title": title,
                "risk_category": normalize_risk_category(item.get("risk_category")),
                "severity": normalize_severity(item.get("severity")),
                "recommendation": str(item.get("recommendation") or "") or None,
                "confirmed": bool(item.get("confirmed", False)),
            }
        )
    return cleaned


def scan_content(content: str, clauses: Sequence[Any]) -> list[dict[str, Any]]:
    """规则比对章节正文与废标条款，返回命中清单.

    仅 confirmed 条款参与；命中来源 = 分类关键词或标题前 4 字出现在正文。
    """
    hits: list[dict[str, Any]] = []
    for clause in clauses:
        if not getattr(clause, "confirmed", False):
            continue
        matched = [kw for kw in _CATEGORY_KEYWORDS.get(clause.risk_category, ()) if kw in content]
        title = getattr(clause, "title", "") or ""
        if not matched and title and title[:4] in content:
            matched = [title[:4]]
        if matched:
            hits.append(
                {
                    "clause_no": clause.clause_no,
                    "title": title,
                    "severity": clause.severity,
                    "risk_category": clause.risk_category,
                    "recommendation": getattr(clause, "recommendation", None),
                    "matched": matched,
                }
            )
    return hits


async def load_project_clauses(db: AsyncSession, project_id: uuid.UUID | str) -> list[Any]:
    """项目级废标条款（跨文档聚合，按条款号排序）."""
    result = await db.execute(
        select(DisqualificationClause)
        .where(DisqualificationClause.project_id == project_id)
        .order_by(DisqualificationClause.clause_no)
    )
    return list(result.scalars().all())


async def scan_project_sections(db: AsyncSession, project_id: uuid.UUID | str) -> dict[str, Any]:
    """扫描项目已生成章节，返回 {章节号: 命中条款清单}（仅 high 条款展示）."""
    clauses = await load_project_clauses(db, project_id)
    high_clauses = [c for c in clauses if c.severity == "high"]
    if not high_clauses:
        return {}
    result = await db.execute(
        select(ProposalSection).where(ProposalSection.project_id == project_id)
    )
    risks: dict[str, list[dict[str, Any]]] = {}
    for section in result.scalars().all():
        hits = scan_content(section.content_md or "", high_clauses)
        if hits:
            risks[section.section_id] = hits
    return risks


async def count_unconfirmed_high(db: AsyncSession, project_id: uuid.UUID | str) -> int:
    """未人工确认的 high 条款计数（导出门禁依据）."""
    result = await db.execute(
        select(func.count())
        .select_from(DisqualificationClause)
        .where(
            DisqualificationClause.project_id == project_id,
            DisqualificationClause.severity == "high",
            DisqualificationClause.confirmed.is_(False),
        )
    )
    return int(result.scalar() or 0)


async def check_chapter_content(project_id: str, content: str) -> list[dict[str, Any]]:
    """validate_node 入口：自建会话加载项目条款并比对章节正文（仅 high 命中）.

    查询带 5s 超时兜底（无 DB 环境 psycopg connect 可能无限挂起）；
    超时/失败抛给调用方（validate_node 按约定降级放行，不阻塞主链路）。
    """
    import asyncio

    async with asyncio.timeout(5.0):
        async with async_session_factory() as db:  # 只读块，无需 commit
            clauses = await load_project_clauses(db, project_id)
    high_clauses = [c for c in clauses if c.severity == "high"]
    return scan_content(content, high_clauses)
