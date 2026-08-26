"""招标解析服务 — 文本抽取 + LLM 结构化提取."""

import io
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.redact import redact
from app.models.document import DisqualificationClause, Document, ScorePoint, TechRequirement
from app.services.llm.rag_service import chunk_text  # noqa: F401


@dataclass
class ParsedTender:
    """招标解析结果."""

    score_points: list[dict]
    tech_requirements: list[dict]
    project_name: str | None = None
    tender_no: str | None = None
    # 施组/技术方案格式要求（排版规范）：[{category, requirement}]，存 Document.meta
    format_requirements: list[dict] = field(default_factory=list)
    # 阶段 E2 术语表：[{term, canonical, desc}]，存 Document.meta.glossary
    glossary: list[dict] = field(default_factory=list)
    # 阶段 H 废标/红线条款：[{clause_no, title, risk_category, severity, recommendation}]
    disqualification_clauses: list[dict] = field(default_factory=list)


# LLM 输入字符预算（DeepSeek 64k 上下文，预留输出与提示词空间）
_PARSE_WINDOW_BUDGET = 40000
# 窗口保留的封面区长度上限（项目名称/编号位于文档开头）
_WINDOW_HEAD_KEEP = 2000
# 评分区定位关键词：细则词优先（含具体评分项与分值），通用词回退；
# 评标办法前附表只有汇总无细则，不应作为首选锚点
_SCORING_KEYWORDS_PRIMARY = ("评分标准", "评分因素", "评分办法", "评分细则")
_SCORING_KEYWORDS_FALLBACK = ("评标办法", "评分")
_TECH_KEYWORDS = ("技术需求", "技术要求", "技术规范")
# 双区域预算分配：评分点为核心交付物，占大头
_SCORING_SHARE = 0.7


def _earliest_anchor(text: str, keywords: tuple[str, ...]) -> int:
    """返回关键词组在文本中最早出现的位置，未命中返回 -1."""
    anchor = -1
    for kw in keywords:
        idx = text.find(kw)
        if idx >= 0 and (anchor == -1 or idx < anchor):
            anchor = idx
    return anchor


def _scoring_anchor(text: str) -> int:
    """评分区锚点：优先细则关键词，未命中回退通用词."""
    anchor = _earliest_anchor(text, _SCORING_KEYWORDS_PRIMARY)
    if anchor == -1:
        anchor = _earliest_anchor(text, _SCORING_KEYWORDS_FALLBACK)
    return anchor


def select_parse_window(text: str, budget: int = _PARSE_WINDOW_BUDGET) -> str:
    """选择覆盖评分/技术需求区的窗口送 LLM.

    招标文件常为封面+目录+正文结构，固定取前 N 字符会让评分标准区落在窗口外，
    导致 LLM 提取结果为空或给出“详见招标文件”类笼统描述。
    策略：封面头部 + 评分区锚定窗口 + 技术要求区锚定窗口；均未命中回退取头部。
    """
    if len(text) <= budget:
        return text

    scoring_anchor = _scoring_anchor(text)
    tech_anchor = _earliest_anchor(text, _TECH_KEYWORDS)
    if scoring_anchor == -1 and tech_anchor == -1:
        return text[:budget]

    head_keep = min(_WINDOW_HEAD_KEEP, budget // 4)
    separator = "\n…\n"
    if scoring_anchor >= 0 and tech_anchor >= 0:
        scoring_budget = int((budget - head_keep) * _SCORING_SHARE)
        tech_budget = budget - head_keep - scoring_budget - 2 * len(separator)
    elif scoring_anchor >= 0:
        scoring_budget = budget - head_keep - len(separator)
        tech_budget = 0
    else:
        scoring_budget = 0
        tech_budget = budget - head_keep - len(separator)

    parts = [text[:head_keep]]
    if scoring_budget > 0:
        start = max(head_keep, scoring_anchor - 500)
        parts.append(text[start : start + scoring_budget])
    if tech_budget > 0:
        start = max(head_keep, tech_anchor - 500)
        parts.append(text[start : start + tech_budget])
    return separator.join(parts)


async def extract_tender_text(file_content: bytes, filename: str) -> str:
    """从 PDF/Word 文件提取纯文本."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(file_content)
    elif ext in ("docx", "doc"):
        return _extract_docx(file_content)
    elif ext == "txt":
        return file_content.decode("utf-8", errors="replace")
    else:
        raise BizError(code=5007, message=f"不支持的文件格式: {ext}")


def _extract_pdf(content: bytes) -> str:
    """PDF 文本提取."""
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except ImportError:
        raise BizError(code=5008, message="pdfplumber 未安装") from None
    except Exception as e:
        raise BizError(code=5007, message=f"PDF 解析失败: {e}") from None


def _extract_docx(content: bytes) -> str:
    """Word 文档文本提取（段落 + 表格，按文档顺序）.

    评分标准/技术需求常置于 docx 表格，只取段落会丢失关键内容。
    """
    try:
        import docx
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = docx.Document(io.BytesIO(content))
        parts: list[str] = []
        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                para = Paragraph(child, doc)
                if para.text.strip():
                    parts.append(para.text)
            elif isinstance(child, CT_Tbl):
                table = Table(child, doc)
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    line = " | ".join(c for c in cells if c)
                    if line:
                        parts.append(line)
        return "\n\n".join(parts)
    except ImportError:
        raise BizError(code=5008, message="python-docx 未安装") from None
    except Exception as e:
        raise BizError(code=5007, message=f"Word 解析失败: {e}") from None


async def parse_tender_with_llm(
    text: str,
    include_tech_requirements: bool = True,
) -> ParsedTender:
    """调用 LLM 对招标文本进行结构化解析.

    include_tech_requirements=False 用于重新解析（只提取评分点）：
    输出 schema 裁掉 tech_requirements，LLM 不再重复提取技术需求。
    """
    # 加载提示词模板
    from app.services.infra.prompt_loader import load_parse_prompt
    from app.services.llm.llm_service import call_llm_with_schema

    # 先选覆盖评分区的窗口，再脱敏（外发 LLM 安全铁律）
    system_prompt, user_prompt = load_parse_prompt(redact(select_parse_window(text)))

    properties: dict = {
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
    if include_tech_requirements:
        properties["tech_requirements"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "is_mandatory": {"type": "boolean"},
                },
                "required": ["seq", "description"],
            },
        }
        required.append("tech_requirements")

    # 格式要求：首次/重新解析均提取（成本可忽略，重新解析时同步刷新）
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

    # 阶段 E2 术语表：缩写/别名 → 规范全称，生成链路统一术语
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

    # 阶段 H 废标/红线条款：触发废标的实质性要求（资质/工期/签章/暗标/格式/偏离）
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
    )

    return ParsedTender(
        score_points=result.get("score_points", []),
        # 重新解析只提取评分点：提示词正文仍含技术需求指令，真实 LLM 可能照常输出，
        # 此处丢弃兜底，保证不写入 tech_requirements
        tech_requirements=result.get("tech_requirements", []) if include_tech_requirements else [],
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
) -> tuple[int, int]:
    """将解析结果写入评分点和技术需求表."""
    # 保存评分点
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

    # 保存技术需求
    tr_count = 0
    for tr_data in parsed.tech_requirements:
        tr = TechRequirement(
            project_id=project_id,
            doc_id=doc_id,
            seq=tr_data["seq"],
            description=tr_data["description"],
            category=tr_data.get("category"),
            is_mandatory=tr_data.get("is_mandatory", False),
        )
        db.add(tr)
        tr_count += 1

    # 阶段 H：保存废标/红线条款（枚举归一，缺 title 丢弃）
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

    # 更新文档状态与格式要求/术语表（存 meta；整体替换新 dict 确保 JSON 列标记脏）
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
    return sp_count, tr_count
