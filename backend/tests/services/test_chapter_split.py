"""章节子节切分（chapter_service）与编号自然序（core.sorting）单元测试."""

from app.core.sorting import is_nested_sections, natural_sort_key, numbered_sections
from app.services.proposal.chapter_service import split_chapter_to_sections

TREE = [{"title": "项目背景"}, {"title": "建设目标"}]


class TestNumberedSections:
    def test_string_sections_returns_empty(self) -> None:
        assert numbered_sections(["背景", "目标"], "1") == []
        assert not is_nested_sections(["背景"])
        assert is_nested_sections([{"title": "背景"}])

    def test_nested_numbering(self) -> None:
        tree = [{"title": "A", "children": [{"title": "A1"}]}, {"title": "B"}]
        assert numbered_sections(tree, "3") == [("3.1", "A"), ("3.1.1", "A1"), ("3.2", "B")]


class TestSplitChapterToSections:
    def test_string_sections_not_split(self) -> None:
        """string[] 大纲（无子节）保持章级存储（向后兼容）."""
        assert split_chapter_to_sections("## A\nxx", ["A", "B"], "1") == []

    def test_split_by_heading(self) -> None:
        content = "## 项目背景\n背景内容\n\n## 建设目标\n目标内容"
        out = split_chapter_to_sections(content, TREE, "1")
        assert [s["section_id"] for s in out] == ["1.1", "1.2"]
        assert "背景内容" in out[0]["content"]
        assert "目标内容" in out[1]["content"]
        assert out[0]["title"] == "项目背景"

    def test_numbered_heading_tolerated(self) -> None:
        """正文标题带编号（## 1.1 项目背景）同样命中."""
        content = "## 1.1 项目背景\nt1\n## 1.2 建设目标\nt2"
        out = split_chapter_to_sections(content, TREE, "1")
        assert [s["section_id"] for s in out] == ["1.1", "1.2"]

    def test_prefix_text_merged_into_first(self) -> None:
        """首个命中标题之前的前置文本并入首个子节."""
        content = "引言段落\n## 项目背景\nt1\n## 建设目标\nt2"
        out = split_chapter_to_sections(content, TREE, "1")
        assert "引言段落" in out[0]["content"]
        assert "引言段落" not in out[1]["content"]

    def test_unmatched_section_merged_into_previous(self) -> None:
        """未命中的子节不产生空行（其内容并入前一子节）."""
        tree = [{"title": "项目背景"}, {"title": "缺失子节"}, {"title": "建设目标"}]
        content = "## 项目背景\nt1\n## 建设目标\nt2"
        out = split_chapter_to_sections(content, tree, "1")
        assert [s["section_id"] for s in out] == ["1.1", "1.3"]

    def test_all_unmatched_into_first(self) -> None:
        """全部标题未命中：整章并入首个子节（不阻塞）."""
        out = split_chapter_to_sections("纯文本无标题", TREE, "2")
        assert len(out) == 1
        assert out[0]["section_id"] == "2.1"
        assert out[0]["content"] == "纯文本无标题"

    def test_nested_tree_split(self) -> None:
        """三级嵌套树按编号切分（## 与 ### 均识别）."""
        tree = [{"title": "A", "children": [{"title": "A1"}]}, {"title": "B"}]
        content = "## A\na段\n### A1\na1段\n## B\nb段"
        out = split_chapter_to_sections(content, tree, "3")
        assert [s["section_id"] for s in out] == ["3.1", "3.1.1", "3.2"]
        assert "a段" in out[0]["content"]
        assert "a1段" in out[1]["content"]
        assert "b段" in out[2]["content"]


class TestNaturalSortKey:
    def test_natural_order(self) -> None:
        """自然序：1 < 1.1 < 1.2 < 1.10 < 2 < 10（修复字典序 10 < 2）."""
        nos = ["10", "2", "1.10", "1.2", "1.1", "1"]
        assert sorted(nos, key=natural_sort_key) == ["1", "1.1", "1.2", "1.10", "2", "10"]
