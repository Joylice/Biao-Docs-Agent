"""Markdown → DSL JSON 解析器.

将 LLM 生成的 Markdown 文本解析为结构化 ProposalContent DSL JSON。
设计原则：
1. 容错优先——未知格式降级为 paragraph block，不报错阻塞（LLM 输出不规范是常态）
2. 块级分割——按空行（\n\n）拆分段落后逐段匹配，减少跨段落解析复杂度
3. 纯 Python 实现——不依赖 markdown-it（前端有对应实现，后端用正则即可覆盖投标方案文档元素）

支持的 Markdown 语法：
- 标题：## ~ ######（对应 heading level 2~6）
- 段落：纯文本
- 无序列表：- / * / + 开头
- 有序列表：1. / 2. 开头
- 表格：| a | b | 管道表格（含对齐分隔行）
- 图片：![alt](url)
- 代码块：```language ... ```
"""

from __future__ import annotations

import re

from app.services.content.dsl_types import (
    DSL_VERSION,
    Block,
    BlockType,
    ListItem,
    ProposalContent,
)

# ── 正则模式 ──────────────────────────────────────────────

# 标题：## 标题 ~ ###### 标题（# 后可有空格）
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")

# 无序列表项：- / * / + 开头（后有空格）
_UNORDERED_RE = re.compile(r"^[-*+]\s+(.*)$")

# 有序列表项：1. / 2. 开头
_ORDERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")

# 缩进检测（2+ 空格或 1+ tab）
_INDENT_RE = re.compile(r"^(\s{2,}|\t+)")

# 图片：![alt](url)
_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")

# 代码块围栏
_CODE_FENCE_RE = re.compile(r"^```(\w*)\s*$")

# 表格行：| cell | cell |
_TABLE_ROW_RE = re.compile(r"^\|(.*)\|\s*$")

# 表格分隔行：|---|---| 或 |:---|:---:|---:|
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def parse_to_blocks(markdown: str) -> list[Block]:
    """将 Markdown 文本解析为 Block 列表.

    按空行分割段落后逐段匹配，未匹配的段落降级为 paragraph block.
    """
    if not markdown or not markdown.strip():
        return []

    lines = markdown.split("\n")
    blocks: list[Block] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            i += 1
            continue

        # 代码块（多行，需找到结束围栏）
        fence = _CODE_FENCE_RE.match(stripped)
        if fence:
            language = fence.group(1) or None
            code_lines: list[str] = []
            i += 1
            while i < len(lines):
                if _CODE_FENCE_RE.match(lines[i].strip()):
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            blocks.append(
                Block(
                    type=BlockType.CODE_BLOCK,
                    content="\n".join(code_lines),
                    language=language,
                )
            )
            continue

        # 表格（需至少 3 行：表头 + 分隔行 + 数据行）
        if (
            _TABLE_ROW_RE.match(stripped)
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1].strip())
        ):
            headers = _parse_table_cells(stripped)
            i += 2  # 跳过表头和分隔行
            rows: list[list[str]] = []
            while i < len(lines):
                row_stripped = lines[i].strip()
                if not row_stripped:
                    break
                if _TABLE_ROW_RE.match(row_stripped):
                    rows.append(_parse_table_cells(row_stripped))
                    i += 1
                else:
                    break
            blocks.append(
                Block(
                    type=BlockType.TABLE,
                    headers=headers,
                    rows=rows,
                    style="grid",
                )
            )
            continue

        # 图片（单行独占）
        img_match = _IMAGE_RE.match(stripped)
        if img_match:
            blocks.append(
                Block(
                    type=BlockType.IMAGE,
                    alt=img_match.group(1),
                    url=img_match.group(2),
                )
            )
            i += 1
            continue

        # 标题
        h_match = _HEADING_RE.match(stripped)
        if h_match:
            level = len(h_match.group(1))
            content = h_match.group(2).strip()
            blocks.append(
                Block(
                    type=BlockType.HEADING,
                    level=level,
                    content=content,
                )
            )
            i += 1
            continue

        # 列表（无序/有序，含嵌套）
        if _UNORDERED_RE.match(stripped) or _ORDERED_RE.match(stripped):
            items, ordered, i = _parse_list(lines, i)
            blocks.append(
                Block(
                    type=BlockType.LIST,
                    items=items,
                    ordered=ordered,
                )
            )
            continue

        # 段落（连续非空非格式行聚合为一个 paragraph）
        para_lines: list[str] = []
        while i < len(lines):
            s = lines[i].strip()
            if not s:
                break
            # 遇到下一个块级元素则停止
            if (
                _HEADING_RE.match(s)
                or _CODE_FENCE_RE.match(s)
                or _IMAGE_RE.match(s)
                or _UNORDERED_RE.match(s)
                or _ORDERED_RE.match(s)
                or (
                    _TABLE_ROW_RE.match(s)
                    and i + 1 < len(lines)
                    and _TABLE_SEP_RE.match(lines[i + 1].strip())
                )
            ):
                break
            para_lines.append(s)
            i += 1
        if para_lines:
            blocks.append(
                Block(
                    type=BlockType.PARAGRAPH,
                    content=" ".join(para_lines),
                )
            )
        continue

    return blocks


def _parse_table_cells(row: str) -> list[str]:
    """解析表格行单元格：| a | b | → ['a', 'b']."""
    match = _TABLE_ROW_RE.match(row)
    if not match:
        return []
    inner = match.group(1)
    return [c.strip() for c in inner.split("|")]


def _indent_level(line: str) -> int:
    """计算缩进层级：每 2 空格或 1 tab = 1 级。0 = 无缩进."""
    level = 0.0  # 半级缩进（2 空格）会出现 .5，故用 float 累计
    for ch in line:
        if ch == " ":
            level += 0.5
        elif ch == "\t":
            level += 1
        else:
            break
    return int(level)


def _parse_list(lines: list[str], start: int) -> tuple[list[ListItem], bool, int]:
    """解析列表块（含嵌套子项）— 基于缩进栈的非递归实现.

    返回 (items, ordered, next_index)。
    嵌套规则：缩进 2+ 空格的列表项视为上一级的子项。
    """
    items: list[ListItem] = []
    ordered = False
    i = start
    # 栈：[(indent_level, ListItem)]，栈底为根级列表
    stack: list[tuple[int, ListItem]] = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            # 空行后若非列表项则结束
            if i < len(lines):
                next_stripped = lines[i].strip()
                if not (_UNORDERED_RE.match(next_stripped) or _ORDERED_RE.match(next_stripped)):
                    break
            continue

        level = _indent_level(line)
        sub_stripped = line.lstrip()
        u_match = _UNORDERED_RE.match(sub_stripped)
        o_match = _ORDERED_RE.match(sub_stripped)

        if u_match or o_match:
            # 确定列表类型（首个列表项）
            if not ordered and not items and not stack:
                ordered = bool(o_match)

            # 上面的 `or` 已保证至少一个匹配非 None；分支化以满足类型收窄
            if u_match is not None:
                content = u_match.group(1).strip()
            else:
                assert o_match is not None
                content = o_match.group(2).strip()
            item = ListItem(content=content)

            # 弹栈到当前层级或更浅
            while stack and stack[-1][0] >= level:
                stack.pop()

            if not stack:
                # 根级
                items.append(item)
            else:
                # 子级 → 归属到父项 children
                stack[-1][1].children.append(item)

            stack.append((level, item))
            i += 1
        else:
            # 非列表项 → 检查是否为缩进续行
            if level > 0 and stack:
                # 归属为最后 item 的续行
                stack[-1][1].content += " " + sub_stripped
                i += 1
            else:
                break  # 非缩进行非列表项 → 结束

    return items, ordered, i


def md_to_dsl(markdown: str) -> ProposalContent:
    """将 Markdown 文本解析为 ProposalContent DSL 文档.

    主入口：LLM 生成 → Markdown → DSL JSON → 落库 content_dsl.
    """
    blocks = parse_to_blocks(markdown)
    return ProposalContent(version=DSL_VERSION, blocks=blocks)
