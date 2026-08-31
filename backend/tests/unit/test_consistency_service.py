"""consistency_service 单测 — 全文一致性检查（mock 直通/正常解析/非法降级）."""

import pytest

from app.services.proposal.consistency_service import check_consistency

CHAPTERS = {"1": "# 概述\n\n内容A", "2": "# 架构\n\n内容B"}
OUTLINE = [
    {"chapter_no": "1", "title": "概述"},
    {"chapter_no": "2", "title": "架构"},
]


async def _mock_enabled(_mock=None) -> bool:
    return True


async def _not_mock(_mock=None) -> bool:
    return False


@pytest.mark.asyncio
async def test_mock_mode_returns_empty_issues(monkeypatch) -> None:
    """mock 模式返回空 issues（不调 LLM，保持 E2E 确定性）."""

    async def fake_llm(**kwargs):
        raise AssertionError("mock 模式不应调用 LLM")

    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _mock_enabled)
    monkeypatch.setattr("app.services.proposal.consistency_service.call_llm_with_schema", fake_llm)
    assert await check_consistency(CHAPTERS, OUTLINE) == []


@pytest.mark.asyncio
async def test_empty_chapters_returns_empty(monkeypatch) -> None:
    """无章节内容时不检查."""
    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _not_mock)
    assert await check_consistency({}, OUTLINE) == []


@pytest.mark.asyncio
async def test_parses_issues_from_llm(monkeypatch) -> None:
    """LLM 返回 issues 列表 → 原样透传（含 chapter_no/type/description/fixable）."""
    issues = [
        {
            "chapter_no": "2",
            "type": "terminology",
            "description": "第2章称'应用服务器'，第1章称'业务服务器'",
            "fixable": True,
        }
    ]

    async def fake_llm(**kwargs):
        return {"issues": issues}

    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _not_mock)
    monkeypatch.setattr("app.services.proposal.consistency_service.call_llm_with_schema", fake_llm)
    result = await check_consistency(CHAPTERS, OUTLINE)
    assert result == issues


@pytest.mark.asyncio
async def test_invalid_response_degrades_to_empty(monkeypatch) -> None:
    """响应结构非法（issues 非列表/条目非 dict）→ 过滤降级，不抛异常."""

    async def fake_llm_bad(**kwargs):
        return {"issues": "不是列表"}

    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _not_mock)
    monkeypatch.setattr(
        "app.services.proposal.consistency_service.call_llm_with_schema", fake_llm_bad
    )
    assert await check_consistency(CHAPTERS, OUTLINE) == []

    async def fake_llm_mixed(**kwargs):
        return {"issues": [{"chapter_no": "1", "description": "重复段落"}, "脏数据"]}

    monkeypatch.setattr(
        "app.services.proposal.consistency_service.call_llm_with_schema", fake_llm_mixed
    )
    result = await check_consistency(CHAPTERS, OUTLINE)
    assert result == [{"chapter_no": "1", "description": "重复段落"}]


@pytest.mark.asyncio
async def test_full_text_sent_in_outline_order(monkeypatch) -> None:
    """全文按大纲顺序拼接送检（章节号+标题+正文）."""
    captured = {}

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        return {"issues": []}

    monkeypatch.setattr("app.services.infra.settings_service.is_mock_enabled", _not_mock)
    monkeypatch.setattr("app.services.proposal.consistency_service.call_llm_with_schema", fake_llm)
    await check_consistency(CHAPTERS, OUTLINE)
    prompt = captured["user_prompt"]
    assert prompt.index("第1章") < prompt.index("第2章")
    assert "内容A" in prompt and "内容B" in prompt
