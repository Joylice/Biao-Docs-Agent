"""招标解析服务 — 文本抽取 + LLM 结构化提取."""

import io
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.redact import redact
from app.models.document import Document, ScorePoint, TechRequirement
from app.services.rag_service import chunk_text  # noqa: F401


@dataclass
class ParsedTender:
    """招标解析结果."""

    score_points: list[dict]
    tech_requirements: list[dict]
    project_name: str | None = None
    tender_no: str | None = None


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
    """Word 文档文本提取."""
    try:
        import docx

        doc = docx.Document(io.BytesIO(content))
        return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        raise BizError(code=5008, message="python-docx 未安装") from None
    except Exception as e:
        raise BizError(code=5007, message=f"Word 解析失败: {e}") from None


async def parse_tender_with_llm(
    text: str,
) -> ParsedTender:
    """调用 LLM 对招标文本进行结构化解析."""
    from app.services.llm_service import call_llm_with_schema

    # 加载提示词模板
    from app.services.prompt_loader import load_parse_prompt

    # 招标原文拼接提示词前脱敏（外发 LLM 安全铁律）
    system_prompt, user_prompt = load_parse_prompt(redact(text[:8000]))  # 截断避免超长

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
                    "properties": {
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
                        "tech_requirements": {
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
                        },
                    },
                    "required": ["score_points", "tech_requirements"],
                },
            },
        },
    )

    return ParsedTender(
        score_points=result.get("score_points", []),
        tech_requirements=result.get("tech_requirements", []),
        project_name=result.get("project_name"),
        tender_no=result.get("tender_no"),
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

    # 更新文档状态
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.status = "parsed"

    await db.flush()
    return sp_count, tr_count
