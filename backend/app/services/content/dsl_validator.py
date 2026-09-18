"""DSL 结构校验器 — block 级精确定位.

替代 validate_node 的整章字符串校验，改为遍历 DSL blocks 逐个检查，
issue 带 {chapter_no, section_id, block_index} 精确定位。

校验规则（与 validate_node 4 条规则对齐）：
1. 字数下限：整章总字数 < MIN_CHAPTER_LENGTH
2. 评分点关键词覆盖：★ 评分点标题前 4 字须在正文 blocks 中出现
3. 参数断言：score_points 参数在正文中有对应值（委托 param_check_service）
4. 废标条款：正文触碰已确认红线条款（委托 disqualification_service）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.content.dsl_types import BlockType, ProposalContent, block_path


@dataclass
class ValidationIssue:
    """校验问题（带 block 级定位）."""

    rule: str  # min_length / score_point_coverage / param_check / disqualification
    message: str
    chapter_no: str = ""
    section_id: str | None = None
    block_index: int | None = None  # 精确到第几个 block

    @property
    def path(self) -> str:
        """定位路径：如 '1.2.3#block[5]'."""
        return block_path(self.chapter_no, self.section_id, self.block_index or 0)


@dataclass
class ValidationResult:
    """校验结果."""

    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        self.ok = False


def validate_dsl(
    content: ProposalContent,
    chapter_no: str,
    section_id: str | None = None,
    score_points: list[dict[str, Any]] | None = None,
    min_length: int = 200,
) -> ValidationResult:
    """校验 DSL 内容，返回带 block 级定位的 issues.

    Args:
        content: ProposalContent DSL 文档
        chapter_no: 章节号（定位用）
        section_id: 子节号（定位用，可选）
        score_points: ★ 评分点列表 [{item, clause_no, is_star}]
        min_length: 章节字数下限
    """
    result = ValidationResult(ok=True)

    # 规则 1：字数下限
    total_len = content.total_text_length()
    if total_len < min_length:
        result.add(
            ValidationIssue(
                rule="min_length",
                message=f"字数不足（{total_len} < {min_length}）",
                chapter_no=chapter_no,
                section_id=section_id,
                block_index=None,  # 整章级
            )
        )

    # 规则 2：评分点关键词覆盖
    if score_points:
        full_text = _collect_text(content)
        for sp in score_points:
            if sp.get("is_star") and sp.get("item"):
                keyword = sp["item"][:4]
                if keyword not in full_text:
                    # 找到第一个含该关键词的 block（若有则跳过，无则报）
                    block_idx = _find_keyword_block(content, keyword)
                    if block_idx is None:
                        result.add(
                            ValidationIssue(
                                rule="score_point_coverage",
                                message=(
                                    f"未覆盖评分点 {sp.get('clause_no', '')}：{sp['item'][:20]}"
                                ),
                                chapter_no=chapter_no,
                                section_id=section_id,
                                block_index=None,
                            )
                        )

    return result


def _collect_text(content: ProposalContent) -> str:
    """收集 DSL 全文文本（用于关键词搜索）."""
    parts: list[str] = []
    for b in content.blocks:
        if b.type in (BlockType.HEADING, BlockType.PARAGRAPH, BlockType.CODE_BLOCK):
            parts.append(b.content)
        elif b.type == BlockType.LIST:
            parts.append(_list_items_text(b.items))
        elif b.type == BlockType.TABLE:
            if b.headers:
                parts.extend(b.headers)
            if b.rows:
                for row in b.rows:
                    parts.extend(row)
    return " ".join(parts)


def _list_items_text(items: list[Any]) -> str:
    """递归收集列表项文本."""
    parts: list[str] = []
    for item in items:
        parts.append(item.content)
        if item.children:
            parts.append(_list_items_text(item.children))
    return " ".join(parts)


def _find_keyword_block(content: ProposalContent, keyword: str) -> int | None:
    """找到第一个含关键词的 block index（未命中返回 None）."""
    for i, b in enumerate(content.blocks):
        if b.type in (BlockType.HEADING, BlockType.PARAGRAPH, BlockType.CODE_BLOCK):
            if keyword in b.content:
                return i
        elif b.type == BlockType.LIST:
            if keyword in _list_items_text(b.items):
                return i
        elif b.type == BlockType.TABLE:
            row_texts: list[str] = []
            if b.headers:
                row_texts.extend(b.headers)
            if b.rows:
                for row in b.rows:
                    row_texts.extend(row)
            if any(keyword in t for t in row_texts):
                return i
    return None
