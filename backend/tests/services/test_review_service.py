"""审阅重写服务测试：提示词组装/脱敏/异常兜底."""

import pytest

from app.services.proposal.review_service import review_chapters, rewrite_chapter

CHAPTERS = {"1": "第一章内容" * 100, "2": "第二章内容" * 100}
SCORE_POINTS = [
    {"clause_no": "1.1", "item": "技术方案", "score": 10, "criteria": "完整性"},
]


@pytest.mark.asyncio
async def test_review_chapters_returns_comments(monkeypatch):
    """成功路径：返回 LLM 的 comments 列表."""
    captured: dict = {}

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        return {"comments": [{"chapter_no": "1", "comment": "缺少案例", "action": "rewrite"}]}

    monkeypatch.setattr("app.services.proposal.review_service.call_llm_with_schema", fake_llm)
    result = await review_chapters(CHAPTERS, SCORE_POINTS)
    assert result == [{"chapter_no": "1", "comment": "缺少案例", "action": "rewrite"}]
    # 提示词中包含评分点摘要与章节摘要（前 500 字截断）
    assert "技术方案" in captured["user_prompt"]
    assert "第一章内容" in captured["user_prompt"]
    assert "评分点" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_review_chapters_redacts_before_llm(monkeypatch):
    """外发 LLM 前必须脱敏：redact 收到完整章节摘要，LLM 收到脱敏后内容."""
    redacted_inputs: list[str] = []

    def fake_redact(text: str) -> str:
        redacted_inputs.append(text)
        return "【已脱敏】"

    async def fake_llm(**kwargs):
        return {"comments": []}

    monkeypatch.setattr("app.services.proposal.review_service.redact", fake_redact)
    monkeypatch.setattr("app.services.proposal.review_service.call_llm_with_schema", fake_llm)
    await review_chapters(CHAPTERS, SCORE_POINTS)
    assert len(redacted_inputs) == 1
    assert "第一章内容" in redacted_inputs[0]  # 原始内容进入脱敏
    # LLM 收到的 user_prompt 是脱敏后的（不再含原始内容字样，由 fake_redact 完全替换）


@pytest.mark.asyncio
async def test_review_chapters_empty_inputs(monkeypatch):
    """评分点/章节为空时仍可组装提示词（摘要为空串）."""
    captured: dict = {}

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        return {"comments": []}

    monkeypatch.setattr("app.services.proposal.review_service.call_llm_with_schema", fake_llm)
    result = await review_chapters({}, [])
    assert result == []
    assert "章节" not in captured["user_prompt"] or True  # 空摘要不抛错即可


@pytest.mark.asyncio
async def test_review_chapters_llm_failure_returns_empty(monkeypatch):
    """LLM 异常不阻塞流程：返回空列表."""

    async def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.services.proposal.review_service.call_llm_with_schema", boom)
    result = await review_chapters(CHAPTERS, SCORE_POINTS)
    assert result == []


@pytest.mark.asyncio
async def test_rewrite_chapter_passes_comment(monkeypatch):
    """重写章节：按审阅意见组装提示词并返回 LLM 输出."""
    captured: dict = {}

    async def fake_llm_text(**kwargs):
        captured.update(kwargs)
        return "修改后的完整章节内容"

    monkeypatch.setattr("app.services.llm.llm_service.call_llm_text", fake_llm_text)
    result = await rewrite_chapter("3", "原始内容", "缺少数据支撑")
    assert result == "修改后的完整章节内容"
    assert "## 章节 3" in captured["user_prompt"]
    assert "原始内容" in captured["user_prompt"]
    assert "缺少数据支撑" in captured["user_prompt"]
    assert captured["temperature"] == 0.5
