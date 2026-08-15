"""chapter_service 单测 — RAG 兜底检索必须拿到真实 db session（非 None）."""

import uuid

import pytest

from app.services.chapter_service import generate_chapter

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
