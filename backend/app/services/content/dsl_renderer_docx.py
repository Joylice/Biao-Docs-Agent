"""DSL JSON → python-docx 渲染器.

递归遍历 ProposalContent DSL 树，逐 block 映射到 python-docx API。
替代 export_service.py 中的 split("\n\n") + startswith("##") 字符串解析。
映射关系确定性，零歧义：
  heading    → doc.add_heading(content, level)
  paragraph  → doc.add_paragraph(content)
  list       → doc.add_paragraph(style='List Bullet'/'List Number')
  table      → doc.add_table(headers, rows)
  image      → run.add_picture(url)
  code_block → doc.add_paragraph(content, style='No Spacing')
"""

from __future__ import annotations

import io
from typing import Any

from app.services.content.dsl_types import Block, BlockType, ListItem, ProposalContent


def render_dsl_to_docx(
    doc: Any,
    content: ProposalContent,
    spec: Any | None = None,
    image_loader: Any | None = None,
) -> None:
    """将 ProposalContent DSL 渲染到 python-docx Document.

    Args:
        doc: python-docx Document 实例
        content: ProposalContent DSL 文档
        spec: FormatSpec（可选，控制字体/行距/页边距）
        image_loader: 可选的图片加载函数 (url → bytes)，None 时跳过图片
    """
    from docx.shared import Cm, Pt

    image_width_cm = 15.0  # 默认图片宽度上限

    for block in content.blocks:
        if block.type == BlockType.HEADING:
            level = block.level or 2
            # python-docx heading level 1~9；DSL level 2~6 映射到 docx level 1~5
            docx_level = max(1, level - 1)
            heading = doc.add_heading(block.content, level=docx_level)
            if spec and hasattr(spec, "heading_size_pt") and spec.heading_size_pt:
                for run in heading.runs:
                    run.font.size = Pt(spec.heading_size_pt)

        elif block.type == BlockType.PARAGRAPH:
            para = doc.add_paragraph(block.content)
            if spec:
                _apply_body_format(para, spec)

            # 段内引用标注
            for cite in block.citations:
                label = _citation_label(cite)
                cite_para = doc.add_paragraph(label)
                if spec:
                    _apply_body_format(cite_para, spec)

        elif block.type == BlockType.LIST:
            style_name = "List Number" if block.ordered else "List Bullet"
            _render_list_items(doc, block.items, style_name, spec, level=0)

        elif block.type == BlockType.TABLE:
            _render_table(doc, block)

        elif block.type == BlockType.IMAGE:
            if image_loader:
                try:
                    data = image_loader(block.url)
                    if data:
                        para = doc.add_paragraph()
                        run = para.add_run()
                        width = block.width_cm or image_width_cm
                        run.add_picture(io.BytesIO(data), width=Cm(width))
                    else:
                        doc.add_paragraph(f"[图片: {block.alt}]")
                except Exception:
                    doc.add_paragraph(f"[图片: {block.alt}]")
            else:
                # 无 image_loader 时回退为文本占位
                doc.add_paragraph(f"[图片: {block.alt}]")

        elif block.type == BlockType.CODE_BLOCK:
            # 代码块：等宽字体段落
            para = doc.add_paragraph(block.content)
            for run in para.runs:
                run.font.name = "Courier New"
            if spec:
                _apply_body_format(para, spec)


def _render_list_items(
    doc: Any,
    items: list[ListItem],
    style_name: str,
    spec: Any | None,
    level: int,
) -> None:
    """递归渲染列表项（含嵌套子项）."""
    for item in items:
        try:
            para = doc.add_paragraph(item.content, style=style_name)
        except Exception:
            # style 不存在时回退为普通段落
            para = doc.add_paragraph(item.content)
        if spec:
            _apply_body_format(para, spec)
        if item.children:
            # 嵌套子项用缩进段落
            _render_list_items(doc, item.children, style_name, spec, level + 1)


def _render_table(doc: Any, block: Block) -> None:
    """渲染表格 block → python-docx table."""
    headers = block.headers or []
    rows = block.rows or []
    total_rows = len(headers) + len(rows)

    if total_rows == 0:
        return

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"

    # 表头
    for i, h in enumerate(headers):
        if i < len(table.rows[0].cells):
            table.rows[0].cells[i].text = h

    # 数据行
    for row_data in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row_data):
            if i < len(cells):
                cells[i].text = str(val)


def _apply_body_format(para: Any, spec: Any) -> None:
    """应用正文行距、字体、字号."""
    from docx.oxml.ns import qn
    from docx.shared import Pt

    if hasattr(spec, "line_spacing_fixed_pt") and spec.line_spacing_fixed_pt:
        para.paragraph_format.line_spacing = Pt(spec.line_spacing_fixed_pt)
    elif hasattr(spec, "line_spacing") and spec.line_spacing:
        para.paragraph_format.line_spacing = spec.line_spacing

    for run in para.runs:
        if hasattr(spec, "body_size_pt") and spec.body_size_pt:
            run.font.size = Pt(spec.body_size_pt)
        if hasattr(spec, "body_font") and spec.body_font:
            run.font.name = spec.body_font
            run._element.rPr.rFonts.set(qn("w:eastAsia"), spec.body_font)


def _citation_label(cite: Any) -> str:
    """引用标注文本：【来源：{doc_title} P{page_no}】."""
    title = getattr(cite, "doc_title", "") or ""
    page_no = getattr(cite, "page_no", None)
    if page_no:
        return f"【来源：{title} P{page_no}】"
    return f"【来源：{title}】"
