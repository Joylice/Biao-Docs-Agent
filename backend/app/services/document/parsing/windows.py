"""窗口选择 / 文本抽取 — 自 parse_service 下沉（T1.1）.

职责：
- select_parse_window：长文本截取覆盖评分区 + 技术需求区 + 封面头部；
- extract_tender_text：PDF/DOCX/TXT 文件 → 纯文本；
- _scoring_anchor：评分区锚点定位（细则关键词优先，通用词回退）。

依赖方向：本模块仅依赖 core.exceptions / core.redact，无 service 层依赖。
"""

import io

from app.core.exceptions import BizError

# ── 命名常量（禁止魔法数字，AGENTS.md 铁律 7）──

# LLM 输入字符预算（DeepSeek 64k 上下文，预留输出与提示词空间）
PARSE_WINDOW_BUDGET = 40000
# 窗口保留的封面区长度上限（项目名称/编号位于文档开头）
WINDOW_HEAD_KEEP = 2000
# 评分区定位关键词：细则词优先（含具体评分项与分值），通用词回退；
# 评标办法前附表只有汇总无细则，不应作为首选锚点
SCORING_KEYWORDS_PRIMARY = ("评分标准", "评分因素", "评分办法", "评分细则")
SCORING_KEYWORDS_FALLBACK = ("评标办法", "评分")
TECH_KEYWORDS = ("技术需求", "技术要求", "技术规范")
# 双区域预算分配：评分点为核心交付物，占大头
SCORING_SHARE = 0.7


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
    anchor = _earliest_anchor(text, SCORING_KEYWORDS_PRIMARY)
    if anchor == -1:
        anchor = _earliest_anchor(text, SCORING_KEYWORDS_FALLBACK)
    return anchor


def select_parse_window(text: str, budget: int = PARSE_WINDOW_BUDGET) -> str:
    """选择覆盖评分/技术需求区的窗口送 LLM.

    招标文件常为封面+目录+正文结构，固定取前 N 字符会让评分标准区落在窗口外，
    导致 LLM 提取结果为空或给出"详见招标文件"类笼统描述。
    策略：封面头部 + 评分区锚定窗口 + 技术要求区锚定窗口；均未命中回退取头部。
    """
    if len(text) <= budget:
        return text

    scoring_anchor = _scoring_anchor(text)
    tech_anchor = _earliest_anchor(text, TECH_KEYWORDS)
    if scoring_anchor == -1 and tech_anchor == -1:
        return text[:budget]

    head_keep = min(WINDOW_HEAD_KEEP, budget // 4)
    separator = "\n…\n"
    if scoring_anchor >= 0 and tech_anchor >= 0:
        scoring_budget = int((budget - head_keep) * SCORING_SHARE)
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
