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

    def test_outline_prompt_requires_covered_clauses(self) -> None:
        """大纲提示词要求每章节标注覆盖评分点（covered_clauses）."""
        score_points = [{"clause_no": "4.2.1", "item": "技术方案", "score": 10, "is_star": True}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        assert "covered_clauses" in system, "system_prompt 应说明 covered_clauses 字段"
        assert "covered_clauses" in user, "user_prompt 应给出 covered_clauses 示例"
        assert "4.2.1" in user
        assert "高可用" in user

    def test_outline_prompt_tech_requirements_as_core(self) -> None:
        """提示词必须以技术需求为核心组织大纲（2026-08-16 优化）."""
        score_points = [{"clause_no": "4.2.1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "支持高可用部署", "category": "架构"}]
        system, user = load_outline_prompt(score_points, tech_requirements)
        # 核心指令：明确以技术需求为章节组织依据
        assert "技术需求" in system
        assert any(kw in system for kw in ("为核心", "核心依据", "唯一依据", "主要依据")), (
            "system_prompt 应明确技术需求为核心组织依据"
        )
        # 用户输入中技术需求优先呈现（位于评分点之前），弱化评分点地位
        tr_idx = user.index("高可用")
        sp_idx = user.index("4.2.1")
        assert tr_idx < sp_idx, "user_prompt 中技术需求应先于评分点呈现"

    def test_outline_prompt_score_points_weakened(self) -> None:
        """提示词不得再以评分项/分值为章节划分依据（2026-08-16 优化）."""
        score_points = [{"clause_no": "4.2.1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, _user = load_outline_prompt(score_points, tech_requirements)
        # 旧版强评分驱动指令必须移除
        assert "对应评分项" not in system, "子节粒度不应再以评分项划分"
        assert "所有评分点" not in system, "不应再以覆盖所有评分点为大纲硬约束"

    def test_outline_prompt_chapter_titles_from_tech_requirements(self) -> None:
        """章节标题必须由技术需求派生，禁止直接采用评分项名称（2026-08-16 优化）."""
        score_points = [{"clause_no": "4.1", "item": "质量保证措施", "score": 20}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, _user = load_outline_prompt(score_points, tech_requirements)
        assert "章节标题" in system
        assert "不得直接" in system and "评分项名称" in system, (
            "system_prompt 应禁止直接采用评分项名称作为章节标题"
        )

    def test_outline_prompt_contains_finalized_template(self) -> None:
        """提示词必须固化定稿骨架：6 段核心章节模板（2026-08-16 定稿参考）."""
        score_points = [{"clause_no": "4.1", "item": "技术方案", "score": 10}]
        tech_requirements = [{"description": "高可用", "category": "架构"}]
        system, _user = load_outline_prompt(score_points, tech_requirements)
        for kw in (
            "需求分析",
            "业务流程设计",
            "总体架构设计",
            "详细功能说明",
            "对接方案",
            "培训与运维服务",
        ):
            assert kw in system, f"system_prompt 应包含定稿骨架章节: {kw}"
        assert "需求分析" in system and "培训与运维服务" in system
        # 骨架顺序与命名保持（需求 → 流程 → 架构 → 功能 → 对接 → 培训运维）
        skeleton = [
            "需求分析",
            "业务流程设计",
            "总体架构设计",
            "详细功能说明",
            "对接方案",
            "培训与运维服务",
        ]
        idxs = [system.index(k) for k in skeleton]
        assert idxs == sorted(idxs), "定稿骨架章节应按顺序呈现"

    def test_outline_prompt_contains_gdsz_template(self) -> None:
        """提示词必须固化广东施组定稿模版：2.3 九子节 + 2.4 模块化结构（2026-08-16 定稿）."""
        system, _user = load_outline_prompt([], [])
        # 2.3 总体架构设计的九个固定子节
        for kw in (
            "设计思路",
            "设计原则",
            "设计目标",
            "总体架构图",
            "功能模块图",
            "数据架构",
            "技术架构",
            "业务架构",
            "安全架构",
        ):
            assert kw in system, f"system_prompt 应包含 2.3 固定子节: {kw}"
        # 2.4 详细功能说明的模块化固定结构（章节生成阶段展开）
        for kw in ("系统概述", "需求设计", "功能架构", "功能说明", "界面设计", "业务流程设计"):
            assert kw in system, f"system_prompt 应包含 2.4 模块化结构: {kw}"

    def test_outline_prompt_architecture_subsections_order(self) -> None:
        """2.3 九个固定子节在提示词中按模版顺序呈现（思路→原则→目标→图→架构）."""
        system, _user = load_outline_prompt([], [])
        arch = [
            "设计思路",
            "设计原则",
            "设计目标",
            "总体架构图",
            "功能模块图",
            "数据架构",
            "技术架构",
            "业务架构",
            "安全架构",
        ]
        idxs = [system.index(k) for k in arch]
        assert idxs == sorted(idxs), "2.3 固定子节应按模版顺序呈现"


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
