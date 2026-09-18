"""DSL Block 类型定义 — 投标方案章节内容结构化表示.

Block 类型枚举覆盖投标方案文档的全部元素：
  heading | paragraph | list | table | image | code_block

设计原则：
- 零运行时依赖（纯 Pydantic models，参照 OpenMAIC @openmaic/dsl 的零依赖契约）
- version 字段支持未来迁移（migration ladder）
- 每个 block 有明确的 attrs 子集，样式直接存在节点上（不依赖中间格式表达）
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# DSL 文档版本（参照 OpenMAIC DSL_VERSION；旧文档经 migration ladder 升级）
DSL_VERSION = 1


class BlockType(StrEnum):
    """Block 类型枚举."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    CODE_BLOCK = "code_block"


class Citation(BaseModel):
    """段内引用标注（当前章末追加 → 段内内联）."""

    chunk_id: str = ""
    doc_title: str = ""
    page_no: int | None = None


class ListItem(BaseModel):
    """列表项（支持嵌套 children）."""

    content: str = ""
    children: list[ListItem] = Field(default_factory=list)


class Block(BaseModel):
    """通用 block 基类 — type 字段做 discriminated union."""

    type: BlockType

    # heading
    level: int | None = None  # 2~6 对应 ## ~ ######

    # heading / paragraph / code_block
    content: str = ""

    # paragraph
    citations: list[Citation] = Field(default_factory=list)

    # list
    ordered: bool | None = None
    items: list[ListItem] = Field(default_factory=list)

    # table
    headers: list[str] | None = None
    rows: list[list[str]] | None = None
    style: str | None = None  # grid | noborder

    # image
    url: str = ""
    alt: str = ""
    width_cm: float | None = None

    # code_block
    language: str | None = None

    # 通用样式（字体/颜色等，Phase 3 编辑器适配时启用）
    attrs: dict[str, Any] = Field(default_factory=dict)


class ProposalContent(BaseModel):
    """章节内容 DSL 文档 — 一棵 block 树.

    存储为 JSON 列（ProposalSection.content_dsl / ChapterAssignment.content_dsl），
    渲染/编辑/校验/版本均消费此结构。
    """

    version: int = DSL_VERSION
    blocks: list[Block] = Field(default_factory=list)

    def block_count(self) -> int:
        """block 总数（不含嵌套列表项）."""
        return len(self.blocks)

    def total_text_length(self) -> int:
        """全文字符数（含标题/段落/列表/表格/代码块文本，不含图片）."""
        total = 0
        for b in self.blocks:
            if b.type == BlockType.HEADING or b.type == BlockType.PARAGRAPH:
                total += len(b.content)
            elif b.type == BlockType.LIST:
                total += _list_text_len(b.items)
            elif b.type == BlockType.TABLE:
                if b.headers:
                    total += sum(len(h) for h in b.headers)
                if b.rows:
                    total += sum(len(c) for row in b.rows for c in row)
            elif b.type == BlockType.CODE_BLOCK:
                total += len(b.content)
        return total


def _list_text_len(items: list[ListItem]) -> int:
    """递归计算列表项文本总长."""
    total = 0
    for item in items:
        total += len(item.content)
        if item.children:
            total += _list_text_len(item.children)
    return total


def block_path(chapter_no: str, section_id: str | None, block_index: int) -> str:
    """构造 block 级路径标识（校验 issue 定位用）.

    示例: "1.2.3#block[5]" 表示第 1 章第 2 节第 3 段的第 5 个 block.
    """
    sec = section_id or chapter_no
    return f"{sec}#block[{block_index}]"
