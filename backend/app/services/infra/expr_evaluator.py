"""ExprEvaluator — 轻量 when 条件表达式求值器.

支持的表达式语法：
  - field                    真值判断（非空/非None为真）
  - not field                取反
  - field | length > 0       列表/字符串长度判断
  - field == "value"          等值判断
  - field in ["a","b"]        包含判断
  - expr1 and expr2          逻辑与

不引入 Jinja2 等重依赖，纯 Python 正则 + 求值。
"""

import re
from typing import Any

_NoneWhen = None  # 无 when 条件时默认为真


class ExprEvaluator:
    """轻量表达式求值器（for PromptComposer when 条件）."""

    # and 分割正则（不在引号内的 and）
    _AND_RE = re.compile(r"\band\b")

    # field | length > N 匹配
    _LENGTH_RE = re.compile(r"^(\w+)\s*\|\s*length\s*(>|>=|<|<=|==|!=)\s*(\d+)$")

    # field == "value" 匹配
    _EQUALS_RE = re.compile(r'^(\w+)\s*(==|!=)\s*"([^"]*)"$')

    # field in ["a","b"] 匹配
    _IN_RE = re.compile(r"^(\w+)\s+in\s+\[([^\]]*)\]$")

    def evaluate(self, expr: str | None, context: dict[str, Any]) -> bool:
        """求值 when 表达式.

        Args:
            expr: when 条件表达式（None 或空串 = 始终为真）
            context: 渲染上下文字典

        Returns:
            True = 该片段/section 应注入，False = 跳过
        """
        if not expr or not expr.strip():
            return True

        # 按 and 分割为子表达式，全部为真才为真
        parts = self._split_and(expr.strip())
        return all(self._eval_single(part.strip(), context) for part in parts)

    def _split_and(self, expr: str) -> list[str]:
        """按 and 分割表达式（不在引号内）."""
        # 简单分割：按空白 and 空白切
        return self._AND_RE.split(expr)

    def _eval_single(self, expr: str, context: dict[str, Any]) -> bool:
        """求值单个原子表达式."""
        # not field
        if expr.startswith("not "):
            field = expr[4:].strip()
            return not self._truthy(context.get(field))

        # field | length OP N
        m = self._LENGTH_RE.match(expr)
        if m:
            field, op, n = m.group(1), m.group(2), int(m.group(3))
            val = context.get(field)
            length = len(val) if isinstance(val, (list, str, dict)) else 0
            return self._compare(length, op, n)

        # field == "value" 或 field != "value"
        m = self._EQUALS_RE.match(expr)
        if m:
            field, op, expected = m.group(1), m.group(2), m.group(3)
            actual = context.get(field)
            if op == "==":
                return actual == expected
            else:
                return actual != expected

        # field in ["a","b"]
        m = self._IN_RE.match(expr)
        if m:
            field, items_str = m.group(1), m.group(2)
            actual = context.get(field)
            items = [s.strip().strip('"').strip("'") for s in items_str.split(",")]
            return actual in items

        # 裸字段名（真值判断）
        if re.match(r"^\w+$", expr):
            return self._truthy(context.get(expr))

        # 无法解析的表达式，保守返回 False（不注入）
        return False

    def _truthy(self, val: Any) -> bool:
        """真值判断：None/空列表/空字符串/空字典为假，其余为真."""
        if val is None:
            return False
        return not (isinstance(val, (list, str, dict)) and len(val) == 0)

    def _compare(self, left: int, op: str, right: int) -> bool:
        """数值比较."""
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        return False
