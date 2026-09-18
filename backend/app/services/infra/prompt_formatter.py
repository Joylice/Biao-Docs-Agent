"""PromptFormatter — 结构化数据 → 提示词文本段格式化器.

迁移自 chapter_service.py 199-254 行 + prompt_loader.py 的内联格式化逻辑，
确保输出与原有实现完全一致（逐字节等价）。

支持的格式：
  - bullet_list      list[str]          → "- item1\\n- item2"
  - summary_list     list[dict]          → "- 第N章 标题: 摘要"
  - score_point_list list[dict]          → "- N.N 评分项: 分值X, 标准: ..."
  - risk_list        list[dict]          → "- N.N: 策略"
  - glossary_list    list[dict]          → "- 缩写 → 全称"
  - requirement_list list[dict]          → "- [类别] 描述"
  - raw              str                 → 原样输出
"""

from typing import Any, ClassVar


class PromptFormatter:
    """结构化数据 → 提示词文本段格式化器."""

    def format(self, format_name: str, data: Any) -> str:
        """按指定格式将结构化数据格式化为提示词文本段.

        Args:
            format_name: 格式名（bullet_list / summary_list / ...）
            data: 原始数据（list[dict] / list[str] / str）

        Returns:
            格式化后的文本（空数据返回空字符串）
        """
        method_name = self._FORMAT_MAP.get(format_name, "_format_raw")
        # getattr 取回的可调用对象对 mypy 是 Any；显式落到声明返回类型
        formatted: str = getattr(self, method_name)(data)
        return formatted

    def _format_bullet_list(self, data: Any) -> str:
        """字符串列表 → 项目符号格式."""
        if not data:
            return ""
        return "\n".join(f"- {s}" for s in data)

    def _format_summary_list(self, data: Any) -> str:
        """章节摘要列表 → '- 第N章 标题: 摘要' 格式."""
        if not data:
            return ""
        lines: list[str] = []
        for p in data:
            lines.append(
                f"- 第{p.get('chapter_no', '')}章 {p.get('title', '')}: {p.get('summary', '')}"
            )
        return "\n".join(lines)

    def _format_score_point_list(self, data: Any) -> str:
        """评分点列表 → '- N.N 评分项: 分值X, 标准: ...' 格式.

        对齐 chapter_service.py 第 200-203 行：
        f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
        f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\\n"
        """
        if not data:
            return ""
        lines: list[str] = []
        for sp in data:
            lines.append(
                f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
                f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}"
            )
        return "\n".join(lines)

    def _format_risk_list(self, data: Any) -> str:
        """高风险评分点 → '- N.N: 策略' 格式.

        对齐 chapter_service.py 第 236-238 行：
        f"- {p.get('clause_no', '')}: {p.get('strategy', '')}"
        """
        if not data:
            return ""
        lines: list[str] = []
        for p in data:
            lines.append(f"- {p.get('clause_no', '')}: {p.get('strategy', '')}")
        return "\n".join(lines)

    def _format_glossary_list(self, data: Any) -> str:
        """术语表 → '- 缩写 → 全称' 格式.

        对齐 chapter_service.py 第 246-250 行：
        f"- {g.get('term', '')} → {g.get('canonical', '')}"
        过滤 term 或 canonical 为空的条目。
        """
        if not data:
            return ""
        lines: list[str] = []
        for g in data:
            term = g.get("term", "")
            canonical = g.get("canonical", "")
            if term and canonical:
                lines.append(f"- {term} → {canonical}")
        return "\n".join(lines)

    def _format_requirement_list(self, data: Any) -> str:
        """技术需求 → '- [类别] 描述' 格式.

        对齐 chapter_service.py 第 207-208 行：
        f"- [{tr.get('category', '')}] {tr.get('description', '')}\\n"
        """
        if not data:
            return ""
        lines: list[str] = []
        for tr in data:
            lines.append(f"- [{tr.get('category', '')}] {tr.get('description', '')}")
        return "\n".join(lines)

    def _format_raw(self, data: Any) -> str:
        """原样输出（字符串直接返回，其他类型转字符串）."""
        if data is None:
            return ""
        if isinstance(data, str):
            return data
        return str(data)

    _FORMAT_MAP: ClassVar[dict[str, str]] = {
        "bullet_list": "_format_bullet_list",
        "summary_list": "_format_summary_list",
        "score_point_list": "_format_score_point_list",
        "risk_list": "_format_risk_list",
        "glossary_list": "_format_glossary_list",
        "requirement_list": "_format_requirement_list",
        "raw": "_format_raw",
    }
