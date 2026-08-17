"""技术需求梳理服务 — 基于已确认评分点梳理应答需求并建立映射.

业务流：评分点人工确认（confirmed=true）→ 本服务经 LLM 从评分项内容
（item + criteria + 分值 + 星级）提炼"应答必须满足的技术需求"，
按 sp_clause 回填评分点映射（sp_id），写入 tech_requirements
（source='sp_derived'）。幂等策略：同项目再次梳理先删旧衍生需求再重建。
"""

import json
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models.document import ScorePoint, TechRequirement

# LLM 输出结构（response_format json_schema；DeepSeek 由 llm_service 降级兼容）
_REQUIREMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "is_mandatory": {"type": "boolean"},
                    "sp_clause": {"type": "string"},
                    "related_clauses": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["seq", "description", "sp_clause"],
            },
        }
    },
    "required": ["requirements"],
}


def _sp_key(sp: ScorePoint) -> str:
    """评分点唯一标识：招标文件同一 clause_no 下可能存在多个评分项，叠加 item 区分."""
    return f"{sp.clause_no}|{sp.item}"


def build_requirement_rows(
    raw_items: list[dict],
    clause_map: dict[str, ScorePoint],
    project_id: uuid.UUID,
    fallback_doc_id: uuid.UUID,
    seq_start: int,
) -> list[dict]:
    """将 LLM 输出转为 tech_requirements 写入行（映射回填 + source 标注）.

    - sp_clause 精确匹配评分点唯一标识（clause_no|item）→ sp_id 回填 + source='sp_derived'
    - 降级：LLM 仅写条款号且该条款号在目标评分点中唯一 → 同样视为匹配
    - 匹配不到 → sp_id=None + source='tender'（视为通用需求）
    - seq 从 seq_start 续编，避免与招标原文提取的需求序号冲突
    """
    rows: list[dict] = []
    for offset, raw in enumerate(raw_items):
        description = str(raw.get("description") or "").strip()
        if not description:
            continue
        key = str(raw.get("sp_clause") or "").strip()
        sp = clause_map.get(key)
        if sp is None and key and "|" not in key:
            # 降级容错：仅条款号且唯一 → 视为匹配
            candidates = [v for k, v in clause_map.items() if k.startswith(key + "|")]
            if len(candidates) == 1:
                sp = candidates[0]
        rows.append(
            {
                "project_id": project_id,
                "doc_id": sp.doc_id if sp else fallback_doc_id,
                "seq": seq_start + offset,
                "description": description,
                "category": raw.get("category") or None,
                "is_mandatory": bool(raw.get("is_mandatory", False)),
                "sp_id": sp.id if sp else None,
                "source": "sp_derived" if sp else "tender",
            }
        )
    return rows


def _sp_payload(sp: ScorePoint) -> dict:
    """评分点 → LLM 输入载荷（对齐提示词约定的字段）."""
    return {
        "sp_key": _sp_key(sp),
        "clause_no": sp.clause_no,
        "item": sp.item,
        "score": float(sp.score) if sp.score is not None else None,
        "criteria": sp.criteria,
        "is_star": sp.is_star,
        "risk_level": sp.risk_level,
    }


async def generate_requirements(
    db: AsyncSession,
    project_id: uuid.UUID,
    score_point_ids: list[uuid.UUID] | None = None,
) -> dict:
    """梳理技术需求：取评分点 → LLM 提炼 → 幂等重建 → 映射回填.

    score_point_ids 为 None 时取该项目全部 confirmed=true 的评分点；
    显式传入则按 id 过滤（前端"勾选再梳理"），缺失/跨项目 id 报 4004。
    """
    # 1. 取目标评分点
    if score_point_ids:
        stmt = select(ScorePoint).where(
            ScorePoint.project_id == project_id,
            ScorePoint.id.in_(score_point_ids),
        )
    else:
        stmt = select(ScorePoint).where(
            ScorePoint.project_id == project_id,
            ScorePoint.confirmed.is_(True),
        )
    result = await db.execute(stmt)
    sps = list(result.scalars().all())
    if score_point_ids and len(sps) != len(set(score_point_ids)):
        raise BizError(code=4004, message="部分评分点不存在或不属于该项目")
    if not sps:
        raise BizError(code=4004, message="没有可梳理的评分点，请先在解析确认页确认评分点")

    # 2. LLM 梳理（mock 模式走 llm_service 确定性降级；外发脱敏由其兜底）
    from app.services.llm_service import call_llm_with_schema
    from app.services.prompt_loader import load_requirements_prompt

    system_prompt, user_prompt = load_requirements_prompt(
        json.dumps([_sp_payload(sp) for sp in sps], ensure_ascii=False)
    )
    llm_result = await call_llm_with_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "requirements_result",
                "strict": True,
                "schema": _REQUIREMENTS_SCHEMA,
            },
        },
    )

    # 3. 幂等：先删本项目旧衍生需求（招标原文提取的 tender/存量需求不受影响）
    await db.execute(
        delete(TechRequirement).where(
            TechRequirement.project_id == project_id,
            TechRequirement.source == "sp_derived",
        )
    )

    # 4. seq 从存量最大值续编
    max_seq_result = await db.execute(
        select(func.max(TechRequirement.seq)).where(TechRequirement.project_id == project_id)
    )
    seq_start = (max_seq_result.scalar() or 0) + 1

    # 5. 映射回填并写入（键为 clause_no|item 唯一标识，避免同号评分项互相覆盖）
    clause_map = {_sp_key(sp): sp for sp in sps}
    rows = build_requirement_rows(
        llm_result.get("requirements") or [],
        clause_map,
        project_id=project_id,
        fallback_doc_id=sps[0].doc_id,
        seq_start=seq_start,
    )
    sp_by_id = {sp.id: sp for sp in sps}
    objects: list[TechRequirement] = []
    for row in rows:
        # 主键显式预分配：响应序列化不依赖 flush 后的懒加载（减少额外查询）
        row = dict(row, id=uuid.uuid4())
        tr = TechRequirement(**row)
        db.add(tr)
        objects.append(tr)
    await db.flush()

    items: list[dict] = []
    for tr in objects:
        related = sp_by_id.get(tr.sp_id)
        items.append(
            {
                "id": str(tr.id),
                "seq": tr.seq,
                "description": tr.description,
                "category": tr.category,
                "is_mandatory": tr.is_mandatory,
                "sp_id": str(tr.sp_id) if tr.sp_id else None,
                "source": tr.source,
                "related_sp": {"clause_no": related.clause_no, "item": related.item}
                if related
                else None,
            }
        )

    # 事务约定（BUG-1）：写路径显式提交，后续大纲/章节生成立即可见
    await db.commit()

    mapped = sum(1 for i in items if i["sp_id"])
    return {"total": len(items), "mapped": mapped, "items": items}


async def list_requirements(
    db: AsyncSession,
    project_id: uuid.UUID,
    only_mapped: bool = False,
) -> list[dict]:
    """技术需求列表（LEFT JOIN score_points 携带 related_sp 映射信息）."""
    stmt = (
        select(TechRequirement, ScorePoint)
        .outerjoin(ScorePoint, TechRequirement.sp_id == ScorePoint.id)
        .where(TechRequirement.project_id == project_id)
        .order_by(TechRequirement.seq)
    )
    if only_mapped:
        stmt = stmt.where(TechRequirement.sp_id.isnot(None))
    result = await db.execute(stmt)
    items: list[dict] = []
    for tr, sp in result.all():
        items.append(
            {
                "id": str(tr.id),
                "seq": tr.seq,
                "description": tr.description,
                "category": tr.category,
                "is_mandatory": tr.is_mandatory,
                "sp_id": str(tr.sp_id) if tr.sp_id else None,
                "source": tr.source,
                "related_sp": {"clause_no": sp.clause_no, "item": sp.item} if sp else None,
            }
        )
    return items
