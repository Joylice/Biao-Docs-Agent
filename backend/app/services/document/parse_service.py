"""招标解析服务 — 门面模块（T1.1 降层后）.

实现下沉至 parsing/ 子包，本模块只保留：
1. re-export：保证 `from app.services.document.parse_service import X` 不变；
2. save_parse_result：DB 写入逻辑（依赖 models，不宜放纯逻辑子包）；
3. parse_tender_with_llm：旧入口保留（行为等价 + 降级回退路径）。

门面 < 400 行（G1 判据）。外部 import 与 monkeypatch 语义不变。
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DisqualificationClause, Document, ScorePoint
from app.services.document.parsing.results import ParsedTender  # re-export

# 全部以 PEP 484 显式再导出写法（`X as X`）声明：既满足 mypy strict 的
# no-implicit-reexport，也避免 ruff F401 把「仅再导出」的 import 误删（本仓曾踩坑）。
from app.services.document.parsing.windows import (
    PARSE_WINDOW_BUDGET as PARSE_WINDOW_BUDGET,
)
from app.services.document.parsing.windows import (
    SCORING_KEYWORDS_FALLBACK as SCORING_KEYWORDS_FALLBACK,
)
from app.services.document.parsing.windows import (
    SCORING_KEYWORDS_PRIMARY as SCORING_KEYWORDS_PRIMARY,
)
from app.services.document.parsing.windows import (
    SCORING_SHARE as SCORING_SHARE,
)
from app.services.document.parsing.windows import (
    TECH_KEYWORDS as TECH_KEYWORDS,
)
from app.services.document.parsing.windows import (
    WINDOW_HEAD_KEEP as WINDOW_HEAD_KEEP,
)
from app.services.document.parsing.windows import (
    _earliest_anchor as _earliest_anchor,
)
from app.services.document.parsing.windows import (
    _extract_docx as _extract_docx,
)
from app.services.document.parsing.windows import (
    _extract_pdf as _extract_pdf,
)
from app.services.document.parsing.windows import (
    _scoring_anchor as _scoring_anchor,  # 旧测试 monkeypatch 引用
)
from app.services.document.parsing.windows import (
    extract_tender_text as extract_tender_text,  # worker/tasks.py 与旧测试从此处导入
)
from app.services.document.parsing.windows import (
    select_parse_window as select_parse_window,
)
from app.services.llm.rag_service import chunk_text as chunk_text  # 旧 re-export 保留

# ── 旧常量别名（下划线前缀，被旧代码/测试 monkeypatch 引用）──
_PARSE_WINDOW_BUDGET = PARSE_WINDOW_BUDGET
_WINDOW_HEAD_KEEP = WINDOW_HEAD_KEEP
_SCORING_KEYWORDS_PRIMARY = SCORING_KEYWORDS_PRIMARY
_SCORING_KEYWORDS_FALLBACK = SCORING_KEYWORDS_FALLBACK
_TECH_KEYWORDS = TECH_KEYWORDS
_SCORING_SHARE = SCORING_SHARE


async def parse_tender_with_llm(
    text: str,
) -> ParsedTender:
    """调用 LLM 对招标文本进行结构化解析（旧入口，行为等价保留）.

    P1 阶段：此入口作为 dispatch 降级回退路径，仍走单次 LLM 调用。
    P2+ 阶段：worker/tasks.py 改调 parse_tender_multi_agent，此入口仅降级使用。

    P3：技术需求已全链路移除，不再从 LLM 提取（见 decisions/0002）。
    """
    from app.core.redact import redact
    from app.services.infra.prompt_loader import load_parse_prompt
    from app.services.llm.llm_service import call_llm_with_schema

    system_prompt, user_prompt = load_parse_prompt(redact(select_parse_window(text)))

    properties: dict[str, Any] = {
        "project_name": {"type": "string"},
        "tender_no": {"type": "string"},
        "score_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_no": {"type": "string"},
                    "item": {"type": "string"},
                    "score": {"type": "number"},
                    "criteria": {"type": "string"},
                    "is_star": {"type": "boolean"},
                    "risk_level": {"type": "string"},
                },
                "required": ["clause_no", "item"],
            },
        },
    }
    required = ["score_points"]

    properties["format_requirements"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "requirement": {"type": "string"},
            },
            "required": ["category", "requirement"],
        },
    }

    properties["glossary"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "term": {"type": "string"},
                "canonical": {"type": "string"},
                "desc": {"type": "string"},
            },
            "required": ["term", "canonical"],
        },
    }

    properties["disqualification_clauses"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "clause_no": {"type": "string"},
                "title": {"type": "string"},
                "risk_category": {"type": "string"},
                "severity": {"type": "string"},
                "recommendation": {"type": "string"},
            },
            "required": ["clause_no", "title"],
        },
    }

    result = await call_llm_with_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "tender_parse_result",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        },
        stage_key="parse",
    )

    return ParsedTender(
        score_points=result.get("score_points", []),
        project_name=result.get("project_name"),
        tender_no=result.get("tender_no"),
        format_requirements=result.get("format_requirements", []),
        glossary=result.get("glossary", []),
        disqualification_clauses=result.get("disqualification_clauses", []),
    )


async def save_parse_result(
    db: AsyncSession,
    project_id: uuid.UUID,
    doc_id: uuid.UUID,
    parsed: ParsedTender,
) -> tuple[int]:
    """将解析结果写入：评分点 + 废标/红线条款 + 文档 meta（仅 flush，不 commit）.

    注意：本函数只 `db.add`，**不清除旧行**。清旧由调用方负责 —— 现行唯一调用方
    `worker.tasks.task_parse_tender` 在调用前按 `doc_id` 清除该文档的旧评分点与
    旧废标条款（幂等，防并发 reparse 数据翻倍）。
    """
    sp_count = 0
    for sp_data in parsed.score_points:
        sp = ScorePoint(
            project_id=project_id,
            doc_id=doc_id,
            clause_no=sp_data["clause_no"],
            item=sp_data["item"],
            score=sp_data.get("score"),
            criteria=sp_data.get("criteria"),
            is_star=sp_data.get("is_star", False),
            risk_level=sp_data.get("risk_level"),
        )
        db.add(sp)
        sp_count += 1

    from app.services.proposal.disqualification_service import (
        normalize_risk_category,
        normalize_severity,
    )

    for dq_data in parsed.disqualification_clauses:
        title = str(dq_data.get("title") or "").strip()
        if not title:
            continue
        db.add(
            DisqualificationClause(
                project_id=project_id,
                doc_id=doc_id,
                clause_no=str(dq_data.get("clause_no") or "").strip() or "-",
                title=title,
                risk_category=normalize_risk_category(dq_data.get("risk_category")),
                severity=normalize_severity(dq_data.get("severity")),
                recommendation=dq_data.get("recommendation"),
            )
        )

    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.status = "parsed"
        doc.meta = {
            **(doc.meta or {}),
            "format_requirements": parsed.format_requirements,
            "glossary": parsed.glossary,
        }

    await db.flush()
    return (sp_count,)
