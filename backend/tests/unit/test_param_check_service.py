"""E1 参数比对校验服务测试（阶段 E：★ 评分点参数断言 vs 章节正文）.

规则链路：criteria 抽取断言（≥/不低于/至少 → min；≤/不超过 → max，单位归一化）
→ 正文同单位数值比对；正文无同单位参数（不确定）→ mock 确定性 pass /
真实模式走 review.yaml param_check LLM 比对（redact 外发，异常降级 pass）。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.proposal import param_check_service as pcs


class TestExtractAssertions:
    def test_min_keywords(self) -> None:
        asserts = pcs.extract_assertions("并发能力不低于500路，支持至少100个节点")
        assert {"direction": "min", "value": 500.0, "unit": "路", "raw": "不低于500路"} in asserts
        assert {"direction": "min", "value": 100.0, "unit": "个", "raw": "至少100个"} in asserts

    def test_max_keywords(self) -> None:
        asserts = pcs.extract_assertions("转发延迟不超过500ms")
        assert {"direction": "max", "value": 500.0, "unit": "ms", "raw": "不超过500ms"} in asserts

    def test_multiplier_normalize(self) -> None:
        asserts = pcs.extract_assertions("存储容量不低于2万GB")
        assert asserts[0]["value"] == 20000.0
        assert asserts[0]["unit"] == "GB"

    def test_no_assertion(self) -> None:
        assert pcs.extract_assertions("方案合理可行，措施到位") == []


class TestFindUnitValues:
    def test_multiple_values(self) -> None:
        vals = pcs.find_unit_values("本系统支持600路并发，扩展可达800路", "路")
        assert vals == [600.0, 800.0]

    def test_multiplier_value(self) -> None:
        assert pcs.find_unit_values("提供3万GB存储能力", "GB") == [30000.0]

    def test_no_match(self) -> None:
        assert pcs.find_unit_values("未提及该参数", "路") == []


def _star_sp(criteria: str) -> dict:
    return {"clause_no": "2.1", "item": "性能", "criteria": criteria, "is_star": True}


class TestCheckChapterParams:
    @pytest.mark.asyncio
    async def test_rule_mismatch_min(self) -> None:
        """正文参数低于 ★ 断言下限 → param_mismatch issue."""
        issues = await pcs.check_chapter_params(
            "本系统支持300路并发接入", [_star_sp("并发不低于500路")]
        )
        assert len(issues) == 1
        assert "2.1" in issues[0]

    @pytest.mark.asyncio
    async def test_rule_pass(self) -> None:
        issues = await pcs.check_chapter_params(
            "本系统支持600路并发接入", [_star_sp("并发不低于500路")]
        )
        assert issues == []

    @pytest.mark.asyncio
    async def test_non_star_skipped(self) -> None:
        sp = {"clause_no": "2.2", "item": "性能", "criteria": "并发不低于500路", "is_star": False}
        issues = await pcs.check_chapter_params("本系统支持300路并发接入", [sp])
        assert issues == []

    @pytest.mark.asyncio
    async def test_uncertain_mock_pass(self) -> None:
        """正文无同单位参数 → mock 模式确定性 pass（不阻塞生成）."""
        with patch.object(pcs.settings_service, "is_mock_enabled", AsyncMock(return_value=True)):
            issues = await pcs.check_chapter_params("方案合理可行", [_star_sp("并发不低于500路")])
        assert issues == []

    @pytest.mark.asyncio
    async def test_uncertain_real_llm_fail(self) -> None:
        """真实模式 LLM 比对判不通过 → issue."""
        with (
            patch.object(pcs.settings_service, "is_mock_enabled", AsyncMock(return_value=False)),
            patch.object(
                pcs, "call_llm_text", AsyncMock(return_value='{"pass": false, "reason": "未达标"}')
            ),
        ):
            issues = await pcs.check_chapter_params("方案合理可行", [_star_sp("并发不低于500路")])
        assert len(issues) == 1

    @pytest.mark.asyncio
    async def test_uncertain_llm_error_degrade_pass(self) -> None:
        """LLM 异常降级 pass（参数校验不阻塞交付主链路）."""
        with (
            patch.object(pcs.settings_service, "is_mock_enabled", AsyncMock(return_value=False)),
            patch.object(pcs, "call_llm_text", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            issues = await pcs.check_chapter_params("方案合理可行", [_star_sp("并发不低于500路")])
        assert issues == []
