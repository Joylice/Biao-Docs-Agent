"""对标高风险策略注入提示词测试 — 阶段 D（1.4）.

链路：chapter.yaml 新增「对标要点」段 → load_chapter_prompt 填充 →
generate_chapter 将 benchmark_high_risk 渲染为 `- {clause_no}: {strategy}` 列表（脱敏外发）。
"""

from unittest.mock import patch

import pytest

from app.services.chapter_service import generate_chapter
from app.services.prompt_loader import load_chapter_prompt


class TestLoadChapterPromptBenchmark:
    def test_benchmark_section_rendered(self) -> None:
        """模板含对标要点段，传入列表文本原样渲染."""
        _, user_prompt = load_chapter_prompt(
            chapter_title="项目概述",
            sections=["背景"],
            context="",
            score_points="",
            tech_requirements="",
            benchmark_high_risk="- 1.1: 补充历史案例",
        )
        assert "对标要点" in user_prompt
        assert "- 1.1: 补充历史案例" in user_prompt

    def test_benchmark_default_empty(self) -> None:
        """缺省占位为「无」（不破坏既有调用）."""
        _, user_prompt = load_chapter_prompt(
            chapter_title="项目概述",
            sections=["背景"],
            context="",
            score_points="",
            tech_requirements="",
        )
        assert "对标要点" in user_prompt


class TestGenerateChapterInjection:
    @pytest.mark.asyncio
    async def test_high_risk_points_injected_into_user_prompt(self) -> None:
        """benchmark_high_risk 渲染为列表注入 user_prompt（经脱敏出口）."""
        captured: dict = {}

        async def fake_llm(system_prompt: str, user_prompt: str, **kwargs) -> str:
            captured["user_prompt"] = user_prompt
            return "章节内容"

        with patch("app.services.chapter_service.call_llm_text", fake_llm):
            await generate_chapter(
                chapter={"title": "技术方案", "sections": ["总体设计"]},
                score_points=[],
                tech_requirements=[],
                project_id=__import__("uuid").uuid4(),
                context="参考资料",
                benchmark_high_risk=[{"clause_no": "2.3", "strategy": "突出等保三级合规设计"}],
            )
        assert "- 2.3: 突出等保三级合规设计" in captured["user_prompt"]

    @pytest.mark.asyncio
    async def test_no_high_risk_placeholder(self) -> None:
        captured: dict = {}

        async def fake_llm(system_prompt: str, user_prompt: str, **kwargs) -> str:
            captured["user_prompt"] = user_prompt
            return "章节内容"

        with patch("app.services.chapter_service.call_llm_text", fake_llm):
            await generate_chapter(
                chapter={"title": "技术方案", "sections": ["总体设计"]},
                score_points=[],
                tech_requirements=[],
                project_id=__import__("uuid").uuid4(),
                context="参考资料",
            )
        # 无高风险点时对标要点段为占位文本
        assert "2.3" not in captured["user_prompt"]
