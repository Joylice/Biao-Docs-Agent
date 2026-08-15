"""提示词模板加载器扩展测试."""

from app.services.prompt_loader import (
    load_chapter_prompt,
    load_outline_prompt,
    load_review_prompt,
)


class TestOutlinePrompt:
    """大纲提示词测试."""

    def test_load_outline_prompt(self) -> None:
        """正常加载大纲模板."""
        score_points = [{"clause_no": "1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "支持高可用", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "架构师" in system or "大纲" in system
        assert "技术方案" in user
        assert "高可用" in user


class TestChapterPrompt:
    """章节提示词测试."""

    def test_load_chapter_prompt(self) -> None:
        """正常加载章节模板."""
        _system, user = load_chapter_prompt(
            chapter_title="系统架构",
            sections=["总体架构", "技术选型"],
            context="参考资料内容",
            score_points="- 1.1 架构设计: 10分",
            tech_requirements="- 支持微服务",
        )
        assert "系统架构" in user
        assert "参考资料内容" in user


class TestReviewPrompt:
    """审阅提示词测试."""

    def test_load_review_prompt(self) -> None:
        """正常加载审阅模板."""
        system, user = load_review_prompt(
            chapter_summary="### 章节 1\n架构设计内容...",
            score_points="- 1.1 架构设计: 10分",
        )
        assert "审核" in system or "审阅" in system
        assert "架构设计" in user
