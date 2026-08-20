"""E3 引用溯源测试 — 检索命中 chunk 元数据落库 proposal_sections.citations.

链路：retrieve_node 采集检索命中（chunk_id/doc_title/page_no 去重）写入
state.retrieved_citations → write_node 经 _persist_chapter_content →
_upsert_section(citations=...) 落库；章节行携带引用供导出标注（E4）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents import nodes
from app.models.document import Document
from app.services.rag_service import ChunkResult
from tests.agents.test_nodes import FakeDB

PROJECT_ID = uuid.uuid4()
DOC_A = uuid.uuid4()
DOC_B = uuid.uuid4()


def _chunk(chunk_id: uuid.UUID, doc_id: uuid.UUID, page_no: int | None) -> ChunkResult:
    return ChunkResult(
        chunk_id=chunk_id, doc_id=doc_id, content="素材内容", page_no=page_no, score=0.9
    )


class TestRetrieveNodeCitations:
    @pytest.mark.asyncio
    async def test_citations_deduped(self) -> None:
        """检索命中按 chunk_id 去重，补齐文档标题后返回 retrieved_citations."""
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        chunks = [
            _chunk(c1, DOC_A, 3),
            _chunk(c1, DOC_A, 3),  # 重复命中
            _chunk(c2, DOC_B, None),
        ]
        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
            "mounted_doc_ids": None,
            "mounted_kb_ids": None,
        }
        title_result = MagicMock()
        title_result.all.return_value = [(DOC_A, "公司资质材料"), (DOC_B, "历史方案")]
        db = MagicMock()
        db.execute = AsyncMock(return_value=title_result)
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=None)
        with (
            patch.object(nodes, "async_session_factory", lambda: db),
            patch.object(
                nodes.kb_base_service, "resolve_mount_doc_ids", AsyncMock(return_value=None)
            ),
            patch(
                "app.services.rag_service.get_embedding",
                AsyncMock(return_value=[0.1] * 8),
            ),
            patch(
                "app.services.rag_service.retrieve_with_rerank",
                AsyncMock(return_value=chunks),
            ),
        ):
            result = await nodes.retrieve_node(state)
        assert result["current_chapter"] == "1"
        assert result["retrieved_citations"] == [
            {"chunk_id": str(c1), "doc_title": "公司资质材料", "page_no": 3},
            {"chunk_id": str(c2), "doc_title": "历史方案", "page_no": None},
        ]

    @pytest.mark.asyncio
    async def test_retrieve_failure_empty_citations(self) -> None:
        """检索失败降级：context 与 citations 均为空."""
        state = {
            "project_id": str(PROJECT_ID),
            "outline": [{"chapter_no": "1", "title": "概述", "sections": []}],
            "chapters": {},
        }
        with (
            patch.object(nodes, "async_session_factory", lambda: FakeDB({Document: []})),
            patch(
                "app.services.rag_service.get_embedding",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            result = await nodes.retrieve_node(state)
        assert result["retrieved_context"] == ""
        assert result["retrieved_citations"] == []


class TestUpsertSectionCitations:
    @pytest.mark.asyncio
    async def test_new_section_stores_citations(self) -> None:
        db = FakeDB()
        citations = [{"chunk_id": "c1", "doc_title": "材料", "page_no": 3}]
        await nodes._upsert_section(
            db, str(PROJECT_ID), "1", "概述", "正文", citations=citations
        )
        assert db.added[0].citations == citations

    @pytest.mark.asyncio
    async def test_persist_chapter_passes_citations(self) -> None:
        """章节落库统一入口把 citations 写到章级行."""
        db = FakeDB()
        citations = [{"chunk_id": "c1", "doc_title": "材料", "page_no": 3}]
        await nodes._persist_chapter_content(
            db, str(PROJECT_ID), "1", "概述", "# 概述\n\n正文", citations=citations
        )
        assert db.added[0].citations == citations
