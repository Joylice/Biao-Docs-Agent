"""内容改进建议服务测试 — 规则分支确定性 / LLM 分支 / 脱敏 / 降级."""

from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import section_suggest_service, settings_service

SCORE_POINTS = [
    {
        "clause_no": "1",
        "item": "技术方案完整性",
        "score": 10,
        "criteria": "方案完整",
        "is_star": True,
    },
    {"clause_no": "4.1", "item": "质量管理", "score": 8, "criteria": "质量措施", "is_star": False},
]

CHAPTERS = {
    "1": "# 项目概述\n\n本方案覆盖背景与目标说明……",
    "2": "# 技术方案\n\n架构与实现细节……",
}


class TestRuleSuggestions:
    """mock 模式：未覆盖评分点 → 确定性规则建议."""

    @pytest.mark.asyncio
    async def test_uncovered_points_suggest_to_most_relevant_chapter(self, monkeypatch) -> None:
        """内容未提及的评分点 → 建议补充到末章（确定性），severity 随星标."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await section_suggest_service.build_section_suggestions(
            CHAPTERS, SCORE_POINTS
        )
        assert len(suggestions) == 2
        s = suggestions[0]
        assert set(s) == {"chapter_no", "issue", "suggestion", "severity"}
        assert s["issue"] == "未覆盖评分点 1（技术方案完整性）"
        assert s["chapter_no"] == "2", "无关键词匹配 → 末章"
        assert s["severity"] == "high", "星标评分点 → high"
        assert suggestions[1]["severity"] == "medium"
        assert suggestions[1]["chapter_no"] == "2"

    @pytest.mark.asyncio
    async def test_target_chapter_restricts_suggestions(self, monkeypatch) -> None:
        """指定 chapter_no → 仅对该章生成建议."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await section_suggest_service.build_section_suggestions(
            CHAPTERS, SCORE_POINTS, chapter_no="2"
        )
        assert suggestions, "第 2 章未提及评分点，应有建议"
        assert all(s["chapter_no"] == "2" for s in suggestions)

    @pytest.mark.asyncio
    async def test_all_covered_no_suggestions(self, monkeypatch) -> None:
        """章节内容已提及全部评分点 → 空建议列表."""
        monkeypatch.setattr(settings, "llm_mock", True)
        full = {"1": "技术方案完整性 质量管理 均已覆盖……"}
        assert await section_suggest_service.build_section_suggestions(full, SCORE_POINTS) == []

    @pytest.mark.asyncio
    async def test_mock_placeholder_content_falls_back(self, monkeypatch) -> None:
        """mock 占位数据（item=mock 且章节内容含 mock 字样）自洽覆盖 → 确定性兜底建议."""
        monkeypatch.setattr(settings, "llm_mock", True)
        sp = [
            {
                "clause_no": "mock",
                "item": "mock",
                "score": 1,
                "criteria": "mock",
                "is_star": False,
            }
        ]
        chapters = {"mock": "（mock 模式）占位章节内容"}
        suggestions = await section_suggest_service.build_section_suggestions(chapters, sp)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["chapter_no"] == "mock"
        assert "未覆盖" in s["issue"]
        assert s["severity"] == "medium"

    @pytest.mark.asyncio
    async def test_rule_suggestions_are_deterministic(self, monkeypatch) -> None:
        """同输入两次生成 → 建议完全一致."""
        monkeypatch.setattr(settings, "llm_mock", True)
        first = await section_suggest_service.build_section_suggestions(CHAPTERS, SCORE_POINTS)
        second = await section_suggest_service.build_section_suggestions(CHAPTERS, SCORE_POINTS)
        assert first == second


class TestLLMSuggestions:
    """生产模式：LLM 建议 + 失败降级为空."""

    @pytest.mark.asyncio
    async def test_llm_suggestions_passed_through(self, monkeypatch) -> None:
        """LLM 返回建议 → 原样透传（含 chapter_no/issue/suggestion/severity）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))
        llm_result = {
            "suggestions": [
                {
                    "chapter_no": "1",
                    "issue": "缺少验收标准",
                    "suggestion": "补充验收标准小节",
                    "severity": "high",
                }
            ]
        }

        async def fake_llm(**kwargs) -> dict:
            return llm_result

        monkeypatch.setattr("app.services.section_suggest_service.call_llm_with_schema", fake_llm)
        suggestions = await section_suggest_service.build_section_suggestions(
            CHAPTERS, SCORE_POINTS
        )
        assert suggestions == llm_result["suggestions"]

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_empty(self, monkeypatch) -> None:
        """LLM 失败 → 降级为空列表（不报错、不阻塞）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))

        async def boom(**kwargs) -> dict:
            raise RuntimeError("模拟 LLM 故障")

        monkeypatch.setattr("app.services.section_suggest_service.call_llm_with_schema", boom)
        assert await section_suggest_service.build_section_suggestions(CHAPTERS, SCORE_POINTS) == []

    @pytest.mark.asyncio
    async def test_user_prompt_redacted_before_outbound(self, monkeypatch) -> None:
        """外发 LLM 前脱敏（章节内容含敏感信息不落 prompt 原文）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))
        captured: dict = {}

        async def fake_llm(**kwargs) -> dict:
            captured["user_prompt"] = kwargs["user_prompt"]
            return {"suggestions": []}

        monkeypatch.setattr("app.services.section_suggest_service.call_llm_with_schema", fake_llm)
        chapters = {"1": "联系人 13812345678，邮箱 test@x.com"}
        await section_suggest_service.build_section_suggestions(chapters, SCORE_POINTS)
        assert "13812345678" not in captured["user_prompt"]
        assert "138****5678" in captured["user_prompt"]
        assert "test@x.com" not in captured["user_prompt"]
