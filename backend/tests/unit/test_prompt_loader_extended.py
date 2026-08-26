"""提示词模板加载器扩展测试."""

from app.services.infra.prompt_loader import (
    load_chapter_prompt,
    load_outline_prompt,
    load_review_prompt,
)


class TestOutlinePrompt:
    """大纲提示词测试（2026-08-25：评分点为核心纲要）."""

    def test_load_outline_prompt(self) -> None:
        """正常加载大纲模板."""
        score_points = [{"clause_no": "1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "支持高可用", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "架构师" in system or "大纲" in system
        assert "技术方案" in user
        assert "高可用" in user

    def test_outline_prompt_requires_covered_clauses(self) -> None:
        """大纲提示词要求每章节标注覆盖评分点（covered_clauses）."""
        score_points = [{"clause_no": "4.2.1", "item": "技术方案", "score": 10, "is_star": True}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "covered_clauses" in system, "system_prompt 应说明 covered_clauses 字段"
        assert "covered_clauses" in user, "user_prompt 应给出 covered_clauses 示例"
        assert "4.2.1" in user
        assert "高可用" in user

    def test_outline_prompt_score_points_as_core(self) -> None:
        """提示词必须以评分点为核心纲要组织大纲（2026-08-25 优化）."""
        score_points = [{"clause_no": "4.2.1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "支持高可用部署", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        # 核心指令：明确以评分点为章节组织依据
        assert "评分点" in system
        assert any(kw in system for kw in ("核心纲要", "主要依据", "划分依据")), (
            "system_prompt 应明确评分点为核心组织依据"
        )
        # 用户输入中评分点优先呈现（位于通用需求之前）
        sp_idx = user.index("4.2.1")
        tr_idx = user.index("高可用")
        assert sp_idx < tr_idx, "user_prompt 中评分点应先于通用需求呈现"

    def test_outline_prompt_score_points_grouped_into_chapters(self) -> None:
        """提示词应说明按主题合并评分点为一级章节."""
        score_points = [
            {"id": "sp1", "clause_no": "4.1", "item": "系统架构", "score": 20},
            {"id": "sp2", "clause_no": "4.2", "item": "系统安全", "score": 20},
        ]
        tech_requirements = [
            {"sp_id": "sp1", "description": "高可用", "category": "架构"},
            {"sp_id": "sp2", "description": "等保合规", "category": "安全"},
        ]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "分组合并" in system, "system_prompt 应说明评分点按主题分组合并成章"
        # 关联技术需求挂在评分点之下（子节推导来源）
        assert "关联技术需求" in user
        sp1_idx = user.index("4.1")
        ha_idx = user.index("高可用")
        assert sp1_idx < ha_idx, "评分点 4.1 的关联需求应紧随其后"

    def test_outline_prompt_general_reqs_separated(self) -> None:
        """未关联评分点的通用需求单独列出作补充，并入最相关章节."""
        score_points = [{"id": "sp1", "clause_no": "4.1", "item": "系统架构", "score": 20}]
        tech_requirements = [{"sp_id": None, "description": "通用运维要求", "category": "运维"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "通用" in system, "system_prompt 应说明未关联需求的处理方式"
        assert "通用运维要求" in user

    def test_outline_prompt_strategy_and_flags(self) -> None:
        """评分点携带应对策略/星号/风险标记，提示词应保留并强调重点评分点."""
        score_points = [
            {
                "id": "sp1",
                "clause_no": "4.1",
                "item": "系统架构",
                "score": 20,
                "is_star": True,
                "strategy": "承诺满足 99.99% 可用性",
            }
        ]
        tech_requirements = [{"sp_id": "sp1", "description": "高可用", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "应对策略" in system or "策略" in system, (
            "system_prompt 应要求章节内容纲要体现应对策略"
        )
        assert "承诺满足 99.99% 可用性" in user, "user_prompt 应保留评分点应对策略"

    def test_outline_prompt_chapter_titles_from_score_points(self) -> None:
        """章节命名由评分点及关联需求综合提炼，体现项目特征，禁止通用模板标题."""
        score_points = [{"clause_no": "4.1", "item": "质量保证措施", "score": 20}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, _user = load_outline_prompt(score_points, tech_requirements)
        assert "章节命名" in system or "章节标题" in system
        assert "禁止" in system and "通用模板" in system, (
            "system_prompt 应禁止通用模板式标题"
        )


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

    def test_chapter_prompt_contains_module_writing_template(self) -> None:
        """章节提示词必须包含功能模块写作模板（定稿模版 2.4 展开结构）."""
        system, _user = load_chapter_prompt(
            chapter_title="详细功能说明",
            sections=["一张图模块"],
            context="",
            score_points="",
            tech_requirements="",
        )
        for kw in ("系统概述", "需求设计", "功能架构", "功能说明", "界面设计", "业务流程设计"):
            assert kw in system, f"system_prompt 应包含模块写作模板: {kw}"


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
