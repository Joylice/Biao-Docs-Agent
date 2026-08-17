"""chapter_service 单测 — RAG 兜底检索必须拿到真实 db session（非 None）."""

import uuid

import pytest

from app.services.chapter_service import (
    SUMMARY_MAX_LEN,
    extract_chapter_summary,
    flatten_sections,
    generate_chapter,
)

CHAPTER = {"chapter_no": "1", "title": "项目概述", "sections": ["背景"]}
PROJECT_ID = uuid.uuid4()


def _patch_llm(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        return "章节内容"

    monkeypatch.setattr("app.services.chapter_service.call_llm_text", fake_llm)


@pytest.mark.asyncio
async def test_fallback_retrieve_receives_caller_db(monkeypatch) -> None:
    """调用方传入 db 时，兜底检索使用该 session（非 None）."""
    captured = {}

    async def fake_retrieve(**kwargs):
        captured.update(kwargs)
        return []

    async def fake_embedding(text):
        return [0.1, 0.2]

    _patch_llm(monkeypatch)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)

    sentinel_db = object()
    await generate_chapter(
        chapter=CHAPTER,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="",
        db=sentinel_db,
    )
    assert "db" in captured
    assert captured["db"] is not None
    assert captured["db"] is sentinel_db


def test_flatten_sections_keeps_string_list_as_is() -> None:
    """LLM 输出的 string[] 子节原样返回（不追加编号，保持既有提示词形态）."""
    sections = ["设计思路", "安全架构"]
    assert flatten_sections(sections) == sections


def test_flatten_sections_numbers_nested_tree() -> None:
    """二次编辑产物的嵌套树递归推导编号（1 / 1.1 / 1.1.1）."""
    sections = [
        {
            "title": "一张图模块",
            "children": [{"title": "系统概述"}, "界面设计"],
        },
        "对接方案",
    ]
    assert flatten_sections(sections) == [
        "1 一张图模块",
        "1.1 系统概述",
        "1.2 界面设计",
        "2 对接方案",
    ]


def test_flatten_sections_deep_nesting() -> None:
    """任意深度嵌套（模版 5 级形态）编号正确推导."""
    sections = [
        {
            "title": "应急安全管理模块",
            "children": [
                {
                    "title": "全流程协同",
                    "children": [{"title": "功能说明"}],
                }
            ],
        }
    ]
    assert flatten_sections(sections) == ["1 应急安全管理模块", "1.1 全流程协同", "1.1.1 功能说明"]


@pytest.mark.asyncio
async def test_generate_chapter_accepts_nested_sections(monkeypatch) -> None:
    """章节生成兼容二次编辑的嵌套子节树：拍平编号后传入章节提示词."""
    captured = {}

    async def fake_retrieve(**kwargs):
        captured.update(kwargs)
        return []

    async def fake_embedding(text):
        return [0.1]

    async def fake_llm(**kwargs):
        return "章节内容"

    def fake_load_chapter_prompt(**kwargs):
        captured.update(kwargs)
        return "系统提示词", "用户提示词"

    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
    monkeypatch.setattr("app.services.chapter_service.call_llm_text", fake_llm)
    monkeypatch.setattr(
        "app.services.chapter_service.load_chapter_prompt", fake_load_chapter_prompt
    )

    chapter = {
        "chapter_no": "4",
        "title": "详细功能说明",
        "sections": [{"title": "一张图模块", "children": [{"title": "系统概述"}]}],
    }
    await generate_chapter(
        chapter=chapter,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="",
        db=object(),
    )
    assert captured["sections"] == ["1 一张图模块", "1.1 系统概述"]


@pytest.mark.asyncio
async def test_fallback_opens_real_session_when_db_absent(monkeypatch) -> None:
    """调用方未传 db 时，内部经 async_session_factory 打开真实 session（非 None）."""
    captured = {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def fake_retrieve(**kwargs):
        captured.update(kwargs)
        return []

    async def fake_embedding(text):
        return [0.1, 0.2]

    _patch_llm(monkeypatch)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)
    monkeypatch.setattr("app.core.database.async_session_factory", lambda: FakeSession())

    await generate_chapter(
        chapter=CHAPTER,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="",
    )
    assert "db" in captured
    assert captured["db"] is not None
    assert isinstance(captured["db"], FakeSession)


@pytest.mark.asyncio
async def test_no_internal_retrieval_when_context_provided(monkeypatch) -> None:
    """图链路传入检索素材（context 非空）时不触发内部检索，避免图内重复检索."""

    async def fake_retrieve(**kwargs):
        raise AssertionError("context 非空时不应触发内部兜底检索")

    async def fake_embedding(text):
        raise AssertionError("context 非空时不应调用 embedding")

    _patch_llm(monkeypatch)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_embedding)

    content = await generate_chapter(
        chapter=CHAPTER,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="retrieve 节点传入的素材",
    )
    assert content == "章节内容"


@pytest.mark.asyncio
async def test_on_delta_streams_deltas_and_returns_full_text(monkeypatch) -> None:
    """三期 S4：传入 on_delta 时走流式，逐块回调且返回全文."""
    deltas = ["第一段", "第二段", "第三段"]

    async def fake_stream(**kwargs):
        for d in deltas:
            yield d

    monkeypatch.setattr("app.services.chapter_service.call_llm_stream", fake_stream)

    received: list[str] = []

    async def on_delta(delta: str) -> None:
        received.append(delta)

    content = await generate_chapter(
        chapter=CHAPTER,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="素材",
        on_delta=on_delta,
    )
    assert received == deltas
    assert content == "第一段第二段第三段"


@pytest.mark.asyncio
async def test_no_on_delta_keeps_non_stream_path(monkeypatch) -> None:
    """未传 on_delta 时保持非流式调用（向后兼容）."""
    called = {"stream": False}

    async def fake_stream(**kwargs):
        called["stream"] = True
        yield "x"

    _patch_llm(monkeypatch)
    monkeypatch.setattr("app.services.chapter_service.call_llm_stream", fake_stream)

    content = await generate_chapter(
        chapter=CHAPTER,
        score_points=[],
        tech_requirements=[],
        project_id=PROJECT_ID,
        context="素材",
    )
    assert content == "章节内容"
    assert called["stream"] is False


class TestExtractChapterSummary:
    """章节摘要提取 — 去 Markdown 标记、压缩空白、截断 ≤200 字."""

    def test_strips_markdown_markers(self) -> None:
        content = "# 项目概述\n\n## 背景\n\n- 本项目要求高可用部署\n\n1. 支持双机热备"
        summary = extract_chapter_summary(content)
        assert "#" not in summary
        assert "-" not in summary
        assert "高可用部署" in summary
        assert "双机热备" in summary

    def test_truncates_to_max_len(self) -> None:
        content = "字" * 500
        summary = extract_chapter_summary(content)
        assert len(summary) <= SUMMARY_MAX_LEN
        assert len(summary) == SUMMARY_MAX_LEN

    def test_empty_content_returns_empty(self) -> None:
        assert extract_chapter_summary("") == ""
        assert extract_chapter_summary("# \n\n  ") == ""


class TestPriorSummariesInjection:
    """章节间上下文注入 — prior_summaries 进入章节提示词."""

    @pytest.mark.asyncio
    async def test_prior_summaries_passed_to_prompt(self, monkeypatch) -> None:
        """传入 prior_summaries → 提示词构造器收到拼接后的已完成章节摘要."""
        captured = {}

        async def fake_llm(**kwargs):
            return "章节内容"

        def fake_load_chapter_prompt(**kwargs):
            captured.update(kwargs)
            return "系统提示词", "用户提示词"

        _patch_llm(monkeypatch)
        monkeypatch.setattr("app.services.chapter_service.call_llm_text", fake_llm)
        monkeypatch.setattr(
            "app.services.chapter_service.load_chapter_prompt", fake_load_chapter_prompt
        )

        await generate_chapter(
            chapter=CHAPTER,
            score_points=[],
            tech_requirements=[],
            project_id=PROJECT_ID,
            context="素材",
            prior_summaries=[
                {"chapter_no": "1", "title": "项目概述", "summary": "介绍项目背景与建设目标"},
                {"chapter_no": "2", "title": "总体架构", "summary": "采用微服务架构"},
            ],
        )
        assert "第1章" in captured["prior_summaries"]
        assert "项目概述" in captured["prior_summaries"]
        assert "介绍项目背景与建设目标" in captured["prior_summaries"]
        assert "第2章" in captured["prior_summaries"]
        assert "微服务架构" in captured["prior_summaries"]

    @pytest.mark.asyncio
    async def test_no_prior_summaries_passes_placeholder(self, monkeypatch) -> None:
        """首章无已完成摘要 → 传入占位文案（提示词不留空白区块）."""
        captured = {}

        def fake_load_chapter_prompt(**kwargs):
            captured.update(kwargs)
            return "系统提示词", "用户提示词"

        _patch_llm(monkeypatch)
        monkeypatch.setattr(
            "app.services.chapter_service.load_chapter_prompt", fake_load_chapter_prompt
        )

        await generate_chapter(
            chapter=CHAPTER,
            score_points=[],
            tech_requirements=[],
            project_id=PROJECT_ID,
            context="素材",
        )
        assert captured["prior_summaries"] == "（无，本章为全文首章）"

    @pytest.mark.asyncio
    async def test_prompt_template_renders_summaries_and_consistency(self, monkeypatch) -> None:
        """真实模板渲染：user_prompt 含已完成摘要区块，system_prompt 含全文一致性约束."""
        captured = {}

        async def fake_llm(**kwargs):
            captured.update(kwargs)
            return "章节内容"

        monkeypatch.setattr("app.services.chapter_service.call_llm_text", fake_llm)

        await generate_chapter(
            chapter=CHAPTER,
            score_points=[],
            tech_requirements=[],
            project_id=PROJECT_ID,
            context="素材",
            prior_summaries=[
                {"chapter_no": "1", "title": "项目概述", "summary": "介绍项目背景"},
            ],
        )
        assert "介绍项目背景" in captured["user_prompt"]
        assert "一致性" in captured["system_prompt"]


class TestSupplementPointsInjection:
    """评分点覆盖矩阵 — 大纲未覆盖评分点注入补写指令."""

    @pytest.mark.asyncio
    async def test_supplement_points_passed_to_prompt(self, monkeypatch) -> None:
        captured = {}

        def fake_load_chapter_prompt(**kwargs):
            captured.update(kwargs)
            return "系统提示词", "用户提示词"

        _patch_llm(monkeypatch)
        monkeypatch.setattr(
            "app.services.chapter_service.load_chapter_prompt", fake_load_chapter_prompt
        )

        await generate_chapter(
            chapter=CHAPTER,
            score_points=[],
            tech_requirements=[],
            project_id=PROJECT_ID,
            context="素材",
            supplement_points=[{"clause_no": "4.1", "item": "数据安全", "criteria": "需满足"}],
        )
        assert "4.1" in captured["supplement_points"]
        assert "数据安全" in captured["supplement_points"]

    @pytest.mark.asyncio
    async def test_no_supplement_passes_placeholder(self, monkeypatch) -> None:
        captured = {}

        def fake_load_chapter_prompt(**kwargs):
            captured.update(kwargs)
            return "系统提示词", "用户提示词"

        _patch_llm(monkeypatch)
        monkeypatch.setattr(
            "app.services.chapter_service.load_chapter_prompt", fake_load_chapter_prompt
        )

        await generate_chapter(
            chapter=CHAPTER,
            score_points=[],
            tech_requirements=[],
            project_id=PROJECT_ID,
            context="素材",
        )
        assert captured["supplement_points"] == "（无，已确认评分点均已被大纲覆盖）"
