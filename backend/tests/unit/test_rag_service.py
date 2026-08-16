"""RAG 服务测试."""

import uuid
from unittest.mock import MagicMock

import pytest

from app.services import rag_service
from app.services.rag_service import ChunkResult, chunk_text


class TestChunkText:
    """文本分块测试."""

    def test_empty_text_returns_empty(self) -> None:
        """空文本返回空列表."""
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self) -> None:
        """短文本只有一个分块."""
        result = chunk_text("hello world")
        assert len(result) == 1
        assert result[0] == "hello world"

    def test_exact_chunk_size(self) -> None:
        """文本长度等于 chunk_size 时只有一个或两个分块."""
        text = "a" * 500
        result = chunk_text(text, chunk_size=500, overlap=50)
        # 由于 overlap=50, 第二个窗口从 450 开始，会多出一个分块
        assert len(result) <= 2

    def test_multiple_chunks(self) -> None:
        """长文本产生多个分块."""
        text = "a" * 1000
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) >= 2

    def test_overlap_works(self) -> None:
        """重叠区域确保连续性."""
        text = "abcdefghijklmnopqrstuvwxyz"
        result = chunk_text(text, chunk_size=10, overlap=3)
        assert len(result) >= 3
        # 验证相邻块之间有重叠
        for i in range(len(result) - 1):
            # 当前块的末尾应该出现在下一块中
            tail = result[i][-3:]
            assert tail in result[i + 1]

    def test_strips_empty_chunks(self) -> None:
        """空白分块被过滤."""
        text = "hello" + " " * 100 + "world"
        result = chunk_text(text, chunk_size=10, overlap=0)
        for chunk in result:
            assert chunk.strip()

    def test_custom_params(self) -> None:
        """自定义 chunk_size 和 overlap."""
        text = "x" * 200
        result = chunk_text(text, chunk_size=80, overlap=20)
        assert all(len(c) <= 80 for c in result)
        assert len(result) >= 3


class TestSearchMaterials:
    """search_materials — 检索端点服务层（E2E-03 缺口补齐）."""

    @pytest.mark.asyncio
    async def test_returns_chunks_with_doc_titles(self, monkeypatch) -> None:
        """查询 → embedding → 相似度检索 → 补齐文档标题."""
        expected_project_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(db, project_id, query_embedding, top_k=20, threshold=0.3):
            assert project_id == expected_project_id
            assert top_k == 5
            return [
                ChunkResult(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    content="支持高可用部署",
                    page_no=1,
                    score=0.9,
                )
            ]

        class FakeDB:
            async def execute(self, stmt):
                result = MagicMock()
                result.all.return_value = [(doc_id, "product-handbook.pdf")]
                return result

        monkeypatch.setattr(rag_service, "get_embedding", fake_embedding)
        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)

        items = await rag_service.search_materials(FakeDB(), expected_project_id, "高可用", top_k=5)
        assert len(items) == 1
        assert items[0]["chunk_id"] == str(chunk_id)
        assert items[0]["doc_id"] == str(doc_id)
        assert items[0]["title"] == "product-handbook.pdf"
        assert items[0]["content"] == "支持高可用部署"
        assert items[0]["page_no"] == 1
        assert items[0]["score"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_no_hits_returns_empty(self, monkeypatch) -> None:
        """检索无命中返回空列表（不再查标题）."""

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(db, project_id, query_embedding, top_k=20, threshold=0.3):
            return []

        class FakeDB:
            def __init__(self) -> None:
                self.queries = 0

            async def execute(self, stmt):
                self.queries += 1
                raise AssertionError("无命中时不应再查询文档标题")

        monkeypatch.setattr(rag_service, "get_embedding", fake_embedding)
        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)

        items = await rag_service.search_materials(FakeDB(), uuid.uuid4(), "不存在的主题")
        assert items == []
