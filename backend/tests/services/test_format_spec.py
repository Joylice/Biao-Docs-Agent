"""format_spec 单元测试 — 格式要求文本 → docx 排版参数.

覆盖：中文字号映射、字体识别、行距（倍数/固定值）、页边距（单边/合并/毫米）、
默认回退（正文 12pt、行距 1.5、无边距）。
"""

from app.services.format_spec import build_format_spec


class TestDefaults:
    def test_empty_requirements_fallback_defaults(self) -> None:
        """无格式要求 → 正文 12pt、行距 1.5、无边距."""
        spec = build_format_spec(None)
        assert spec.body_size_pt == 12.0
        assert spec.line_spacing == 1.5
        assert spec.line_spacing_fixed_pt is None
        assert spec.body_font is None
        assert spec.heading_size_pt is None
        assert spec.margins_cm == {}

    def test_unparsable_items_fallback_defaults(self) -> None:
        """不可解析文本不改变默认值."""
        spec = build_format_spec(
            [
                {"category": "font_body", "requirement": "字体美观大方"},
                {"category": "line_spacing", "requirement": "行距适中"},
                {"category": "margin", "requirement": "按常规设置"},
            ]
        )
        assert spec.body_size_pt == 12.0
        assert spec.line_spacing == 1.5
        assert spec.margins_cm == {}


class TestFont:
    def test_cn_font_size_mapping(self) -> None:
        """中文字号映射：小四→12、四号→14、小三→15、三号→16."""
        fr = [
            {"category": "font_body", "requirement": "正文宋体小四"},
            {"category": "font_heading", "requirement": "章标题黑体三号"},
        ]
        spec = build_format_spec(fr)
        assert spec.body_font == "宋体"
        assert spec.body_size_pt == 12.0
        assert spec.heading_size_pt == 16.0

    def test_numeric_pt_size(self) -> None:
        spec = build_format_spec([{"category": "font_body", "requirement": "正文 14pt 仿宋"}])
        assert spec.body_size_pt == 14.0
        assert spec.body_font == "仿宋"

    def test_fangsong_gb2312_long_name_first(self) -> None:
        """仿宋_GB2312 优先于 仿宋 匹配."""
        spec = build_format_spec(
            [{"category": "font_body", "requirement": "正文采用仿宋_GB2312四号字"}]
        )
        assert spec.body_font == "仿宋_GB2312"
        assert spec.body_size_pt == 14.0


class TestLineSpacing:
    def test_multiple_line_spacing(self) -> None:
        spec = build_format_spec([{"category": "line_spacing", "requirement": "1.5倍行距"}])
        assert spec.line_spacing == 1.5
        assert spec.line_spacing_fixed_pt is None

    def test_fixed_line_spacing(self) -> None:
        """固定值行距 → fixed_pt 生效、倍数行距置空."""
        spec = build_format_spec([{"category": "line_spacing", "requirement": "固定值28磅"}])
        assert spec.line_spacing_fixed_pt == 28.0
        assert spec.line_spacing is None


class TestMargins:
    def test_combined_margins(self) -> None:
        """上下/左右合并写法展开为四边."""
        spec = build_format_spec([{"category": "margin", "requirement": "上下2.54cm，左右3.17cm"}])
        assert spec.margins_cm == {"top": 2.54, "bottom": 2.54, "left": 3.17, "right": 3.17}

    def test_per_side_margins(self) -> None:
        spec = build_format_spec(
            [{"category": "margin", "requirement": "上边2.5cm 下边2.5 左3.0cm 右2.6cm"}]
        )
        assert spec.margins_cm == {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 2.6}

    def test_mm_unit_converted_to_cm(self) -> None:
        spec = build_format_spec([{"category": "margin", "requirement": "上边距25毫米"}])
        assert spec.margins_cm == {"top": 2.5}


class TestChapterFormat:
    """阶段5：chapter_format（章节格式要求）仅展示，不参与排版映射."""

    def test_chapter_format_not_mapped_to_layout(self) -> None:
        spec = build_format_spec(
            [
                {
                    "category": "chapter_format",
                    "requirement": "章节编号采用1.1/1.2两级，层级不超过三级，每章篇幅不超过50页",
                },
                {"category": "font_body", "requirement": "正文宋体小四"},
            ]
        )
        # chapter_format 不影响任何排版参数；其余分类正常生效
        assert spec.body_font == "宋体"
        assert spec.body_size_pt == 12.0
        assert spec.heading_size_pt is None
        assert spec.line_spacing == 1.5
        assert spec.margins_cm == {}
