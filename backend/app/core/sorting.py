"""章节编号排序与子节编号工具（跨域共享，消除伪耦合）.

从 export_service / chapter_service 提取到 core 层，供 infra / project / proposal /
document 等域统一引用，避免跨域模块级依赖仅为工具函数的情况。
"""


def natural_sort_key(no: str) -> tuple:
    """章节编号自然序排序键：1.1 < 1.2 < 2 < 10（修复字典序 10 < 2 隐患）.

    按 `.` 分段，数字段按数值比较，非数字段按字符串比较（排在同位数字段之后）。
    供 proposal_sections 子节行读取/拼装导出时排序使用。
    """
    parts: list[tuple[int, object]] = []
    for seg in str(no).split("."):
        if seg.isdigit():
            parts.append((0, int(seg)))
        else:
            parts.append((1, seg))
    return tuple(parts)


def is_nested_sections(sections: list) -> bool:
    """sections 是否为嵌套树形态（含 dict 节点）；string[] 视为无子节（章级存储）."""
    return any(isinstance(s, dict) for s in sections or [])


def _numbered_tree(nodes: list, prefix: str, out: list[tuple[str, str]]) -> None:
    """嵌套树递归推导编号标题对 [(no, title)]（与 flatten_sections 编号规则一致）."""
    for i, node in enumerate(nodes, 1):
        if isinstance(node, str):
            if node.strip():
                out.append((f"{prefix}{i}", node.strip()))
        elif isinstance(node, dict):
            title = str(node.get("title", "")).strip()
            if title:
                out.append((f"{prefix}{i}", title))
            children = node.get("children") or []
            if children:
                _numbered_tree(children, f"{prefix}{i}.", out)


def numbered_sections(sections_tree: list, chapter_no: str) -> list[tuple[str, str]]:
    """嵌套树子节编号平铺 [(no, title)]（no = {chapter_no}.{序号…}）.

    string[] 形态（无子节）返回 []，调用方保持章级语义。
    """
    if not is_nested_sections(sections_tree):
        return []
    out: list[tuple[str, str]] = []
    _numbered_tree(sections_tree, f"{chapter_no}.", out)
    return out
