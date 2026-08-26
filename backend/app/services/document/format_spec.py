"""招标格式要求解析 — 将 format_requirements 文本转换为 docx 排版参数.

解析约定：
- 中文字号（初号~小六）按国标映射为 pt；数字形式（12pt/12磅）直接解析。
- 行距支持倍数（1.5倍行距）与固定值（固定值 28 磅）。
- 页边距支持单边（上边 2.5cm）与合并写法（上下 2.54cm 左右 3.17cm），无单位按 cm。
- 无法解析的条目回退默认值：正文 12pt、行距 1.5 倍、页边距沿用 docx 默认。
"""

import re
from dataclasses import dataclass, field

# 中文字号 → pt（国标 GB/T 9704 常用字号）
CN_FONT_SIZE_PT: dict[str, float] = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
    "六号": 7.5,
    "小六": 6.5,
}

# 长名优先，避免「小四」被「四号」误匹配
_CN_SIZE_SORTED = sorted(CN_FONT_SIZE_PT.items(), key=lambda kv: -len(kv[0]))

# 常见中文字体名（长名优先，仿宋_GB2312 先于 仿宋）
FONT_NAMES = ("仿宋_GB2312", "Times New Roman", "微软雅黑", "宋体", "黑体", "楷体", "仿宋", "等线")

_NUM = r"(\d+(?:\.\d+)?)"
_SIZE_PT_RE = re.compile(rf"{_NUM}\s*(?:pt|磅)")
_MARGIN_SIDE_RE = re.compile(rf"(上|下|左|右)(?:边|距)?[^0-9]{{0,4}}{_NUM}\s*(cm|厘米|毫米|mm)?")
_MARGIN_PAIR_RE = re.compile(rf"(上下|左右)(?:边|距)?[^0-9]{{0,4}}{_NUM}\s*(cm|厘米|毫米|mm)?")
_LINE_SPACING_RE = re.compile(rf"{_NUM}\s*(?:倍)?\s*行距|行距[^0-9]{{0,4}}{_NUM}")
_FIXED_SPACING_RE = re.compile(rf"固定值?[^0-9]{{0,4}}{_NUM}\s*(?:pt|磅|行)?")


@dataclass
class FormatSpec:
    """Word 排版参数（None/空表示沿用 docx 默认）."""

    body_font: str | None = None
    body_size_pt: float = 12.0
    heading_size_pt: float | None = None
    line_spacing: float | None = 1.5
    line_spacing_fixed_pt: float | None = None
    margins_cm: dict[str, float] = field(default_factory=dict)


def _parse_size_pt(text: str) -> float | None:
    """解析字号：中文字号优先，其次数字 pt/磅."""
    for name, pt in _CN_SIZE_SORTED:
        if name in text:
            return pt
    m = _SIZE_PT_RE.search(text)
    return float(m.group(1)) if m else None


def _find_font_name(text: str) -> str | None:
    for name in FONT_NAMES:
        if name in text:
            return name
    return None


def _to_cm(value: float, unit: str | None) -> float:
    if unit in ("毫米", "mm"):
        return value / 10
    return value


def _parse_margins(text: str) -> dict[str, float]:
    """解析页边距：先合并写法（上下/左右），再单边，后者不覆盖前者."""
    margins: dict[str, float] = {}
    for pair, num, unit in _MARGIN_PAIR_RE.findall(text):
        value = _to_cm(float(num), unit)
        if pair == "上下":
            margins.setdefault("top", value)
            margins.setdefault("bottom", value)
        else:
            margins.setdefault("left", value)
            margins.setdefault("right", value)
    side_keys = {"上": "top", "下": "bottom", "左": "left", "右": "right"}
    for side, num, unit in _MARGIN_SIDE_RE.findall(text):
        margins.setdefault(side_keys[side], _to_cm(float(num), unit))
    return margins


def _parse_line_spacing(text: str, spec: FormatSpec) -> None:
    fixed = _FIXED_SPACING_RE.search(text)
    if fixed:
        spec.line_spacing_fixed_pt = float(fixed.group(1))
        spec.line_spacing = None
        return
    m = _LINE_SPACING_RE.search(text)
    if m:
        spec.line_spacing = float(m.group(1) or m.group(2))


def build_format_spec(format_requirements: list[dict] | None) -> FormatSpec:
    """将格式要求条目聚合为排版参数；未提供或不可解析时回退默认值."""
    spec = FormatSpec()
    for item in format_requirements or []:
        category = item.get("category")
        text = str(item.get("requirement") or "").strip()
        if not text:
            continue
        if category == "font_body":
            font = _find_font_name(text)
            if font:
                spec.body_font = font
            size = _parse_size_pt(text)
            if size:
                spec.body_size_pt = size
        elif category == "font_heading":
            size = _parse_size_pt(text)
            if size:
                spec.heading_size_pt = size
        elif category == "line_spacing":
            _parse_line_spacing(text, spec)
        elif category == "margin":
            spec.margins_cm.update(_parse_margins(text))
    return spec
