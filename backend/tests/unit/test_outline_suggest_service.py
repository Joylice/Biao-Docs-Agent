"""大纲优化建议服务测试 — 规则分支确定性 / LLM 分支 / apply 纯函数 / 脱敏."""

from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import outline_suggest_service, settings_service
from app.services.outline_suggest_service import apply_outline_suggestions

SCORE_POINTS = [
    {"clause_no": "1", "item": "技术方案完整性", "score": 10, "criteria": "方案完整"},
    {"clause_no": "4.1", "item": "质量管理", "score": 8, "criteria": "质量措施"},
    {"clause_no": "4.2", "item": "进度计划", "score": 8, "criteria": "工期安排"},
]

OUTLINE = [
    {
        "chapter_no": "1",
        "title": "项目概述",
        "sections": ["背景", "目标"],
        "covered_clauses": ["1"],
    },
    {
        "chapter_no": "2",
        "title": "技术方案",
        "sections": ["架构", "实现"],
        "covered_clauses": ["4.1"],
    },
]


class TestRuleSuggestions:
    """mock 模式：覆盖矩阵缺口 → 确定性规则建议（E2E 可断言）."""

    @pytest.mark.asyncio
    async def test_uncovered_points_become_add_section(self, monkeypatch) -> None:
        """未覆盖评分点 → add_section 建议（目标章=末章），字段完整."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["suggestion_type"] == "add_section"
        assert s["target"]["chapter_no"] == "2"
        assert s["target"]["clause_no"] == "4.2"
        assert s["target"]["title"] == "进度计划"
        assert "4.2" in s["reason"]
        assert s["suggested_action"]

    @pytest.mark.asyncio
    async def test_rule_suggestions_are_deterministic(self, monkeypatch) -> None:
        """同输入两次生成 → 建议完全一致（id/内容确定性）."""
        monkeypatch.setattr(settings, "llm_mock", True)
        first = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        second = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        assert first == second

    @pytest.mark.asyncio
    async def test_empty_outline_suggests_add_chapter(self, monkeypatch) -> None:
        """大纲为空 → add_chapter 建议（标题取未覆盖评分点）."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, [])
        assert len(suggestions) == 1
        assert suggestions[0]["suggestion_type"] == "add_chapter"
        assert suggestions[0]["target"]["title"] == "技术方案完整性"

    @pytest.mark.asyncio
    async def test_all_covered_no_suggestions(self, monkeypatch) -> None:
        """全覆盖 → 空建议列表."""
        monkeypatch.setattr(settings, "llm_mock", True)
        full = [
            *OUTLINE,
            {
                "chapter_no": "3",
                "title": "实施计划",
                "sections": [],
                "covered_clauses": ["4.2"],
            },
        ]
        assert await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, full) == []

    @pytest.mark.asyncio
    async def test_mock_placeholder_full_coverage_falls_back(self, monkeypatch) -> None:
        """mock 占位数据（clause_no/covered_clauses 均为 mock）自洽覆盖 → 确定性兜底建议."""
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
        outline = [
            {
                "chapter_no": "mock",
                "title": "mock",
                "sections": ["mock"],
                "covered_clauses": ["mock"],
            }
        ]
        suggestions = await outline_suggest_service.build_outline_suggestions(sp, outline)
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["suggestion_type"] == "add_chapter"
        assert s["target"]["title"] == "补充章节"
        assert s["suggestion_id"]
        # 兜底建议可被 apply 应用（大纲增加一章）
        applied = apply_outline_suggestions(outline, [s["suggestion_id"]])
        assert len(applied) == 2
        assert applied[-1]["title"] == "补充章节"


class TestLLMSuggestions:
    """生产模式：LLM 建议 + 失败降级 + 脱敏."""

    @pytest.mark.asyncio
    async def test_llm_suggestions_get_server_encoded_ids(self, monkeypatch) -> None:
        """LLM 建议的 suggestion_id 由服务端编码（apply 可解码应用）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))

        async def fake_llm(**kwargs) -> dict:
            return {
                "suggestions": [
                    {
                        "suggestion_type": "rename",
                        "target": {"chapter_no": "1", "title": "项目总体概述"},
                        "reason": "标题未突出总体定位",
                        "suggested_action": "改为项目总体概述",
                    }
                ]
            }

        monkeypatch.setattr("app.services.outline_suggest_service.call_llm_with_schema", fake_llm)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        assert len(suggestions) == 1
        assert suggestions[0]["suggestion_type"] == "rename"

        applied = apply_outline_suggestions(OUTLINE, [suggestions[0]["suggestion_id"]])
        assert applied[0]["title"] == "项目总体概述", "编码 id 应可被 apply 解码应用"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rules(self, monkeypatch) -> None:
        """LLM 失败 → 降级为规则建议（不报错）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))

        async def boom(**kwargs) -> dict:
            raise RuntimeError("模拟 LLM 故障")

        monkeypatch.setattr("app.services.outline_suggest_service.call_llm_with_schema", boom)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        assert len(suggestions) == 1
        assert suggestions[0]["suggestion_type"] == "add_section"
        assert suggestions[0]["target"]["clause_no"] == "4.2"

    @pytest.mark.asyncio
    async def test_user_prompt_redacted_before_outbound(self, monkeypatch) -> None:
        """外发 LLM 前脱敏（安全铁律：出口兜底前服务层显式 redact）."""
        monkeypatch.setattr(settings_service, "is_mock_enabled", AsyncMock(return_value=False))
        captured: dict = {}

        async def fake_llm(**kwargs) -> dict:
            captured["user_prompt"] = kwargs["user_prompt"]
            return {"suggestions": []}

        monkeypatch.setattr("app.services.outline_suggest_service.call_llm_with_schema", fake_llm)
        sp = [{"clause_no": "1", "item": "联系人 13812345678", "score": 1, "criteria": "x"}]
        await outline_suggest_service.build_outline_suggestions(sp, [])
        assert "13812345678" not in captured["user_prompt"]
        assert "138****5678" in captured["user_prompt"]


class TestApply:
    """apply_outline_suggestions 纯函数：按 suggestion_id 解码应用."""

    @pytest.mark.asyncio
    async def test_apply_add_section_closes_loop(self, monkeypatch) -> None:
        """规则建议闭环：build → 勾选 → apply 追加小节到目标章（幂等去重）."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, OUTLINE)
        applied = apply_outline_suggestions(OUTLINE, [s["suggestion_id"] for s in suggestions])
        assert applied[0] == OUTLINE[0], "非目标章不变"
        assert applied[1]["sections"] == ["架构", "实现", "进度计划"]

        # 幂等：同一建议重复应用不重复追加
        again = apply_outline_suggestions(applied, [s["suggestion_id"] for s in suggestions])
        assert again[1]["sections"] == ["架构", "实现", "进度计划"]

    @pytest.mark.asyncio
    async def test_apply_add_chapter_appends_new_chapter(self, monkeypatch) -> None:
        """空大纲采纳 add_chapter → 追加新章（章节号递增，带 covered_clauses）."""
        monkeypatch.setattr(settings, "llm_mock", True)
        suggestions = await outline_suggest_service.build_outline_suggestions(SCORE_POINTS, [])
        applied = apply_outline_suggestions([], [suggestions[0]["suggestion_id"]])
        assert len(applied) == 1
        assert applied[0]["chapter_no"] == "1"
        assert applied[0]["title"] == "技术方案完整性"
        assert applied[0]["covered_clauses"] == ["1"]

    @pytest.mark.asyncio
    async def test_apply_rename_updates_title(self, monkeypatch) -> None:
        """rename 建议 → 目标章标题替换."""
        monkeypatch.setattr(settings, "llm_mock", True)
        sid = outline_suggest_service._encode_suggestion_id(
            {
                "suggestion_type": "rename",
                "target": {"chapter_no": "1", "title": "总体概述"},
            }
        )
        applied = apply_outline_suggestions(OUTLINE, [sid])
        assert applied[0]["title"] == "总体概述"
        assert applied[1]["title"] == "技术方案"

    def test_apply_unknown_id_ignored(self) -> None:
        """未知 suggestion_id → 忽略，其余建议正常应用."""
        applied = apply_outline_suggestions(OUTLINE, ["not-a-real-id"])
        assert applied == OUTLINE
