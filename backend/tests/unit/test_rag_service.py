"""RAG 服务测试."""

import uuid
from collections import namedtuple
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services import rag_service
from app.services.rag_service import ChunkResult, chunk_text

# 模拟 KbChunk 检索结果行（含 .distance 属性，与 sqlalchemy Row 对齐）
_ChunkRow = namedtuple("_ChunkRow", "id doc_id content page_no distance")


async def _fake_not_mock(_mock=None) -> bool:
    """非 mock 模式（避免真实读库内配置）."""
    return False


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


class TestRetrieveSimilarDocFilter:
    """retrieve_similar 挂载文档过滤（doc_ids 参数）."""

    @pytest.mark.asyncio
    async def test_doc_ids_filters_only_given_docs(self) -> None:
        """传入 doc_ids 时只检索指定文档的分块，不再查询项目全量文档."""
        project_id = uuid.uuid4()
        doc_a = uuid.uuid4()

        class FakeDB:
            def __init__(self) -> None:
                self.statements = []

            async def execute(self, stmt):
                self.statements.append(str(stmt))
                result = MagicMock()
                result.all.return_value = [
                    _ChunkRow(uuid.uuid4(), doc_a, "挂载文档内容", 1, 0.1),
                ]
                return result

        db = FakeDB()
        results = await rag_service.retrieve_similar(
            db=db,
            project_id=project_id,
            query_embedding=np.array([0.1, 0.2]),
            doc_ids=[doc_a],
        )
        assert len(results) == 1
        assert results[0].doc_id == doc_a
        # 仅查询 KbChunk 表（未先查询 Document 表取全量 doc_ids）
        assert len(db.statements) == 1
        assert "kb_chunks" in db.statements[0]
        assert "documents" not in db.statements[0]

    @pytest.mark.asyncio
    async def test_doc_ids_none_keeps_project_wide_behavior(self) -> None:
        """doc_ids 缺省时按项目全量文档检索（原行为不变）."""
        project_id = uuid.uuid4()
        doc_a = uuid.uuid4()

        class FakeDB:
            def __init__(self) -> None:
                self.calls = 0

            async def execute(self, stmt):
                text = str(stmt)
                result = MagicMock()
                if self.calls == 0 and "documents" in text:
                    result.all.return_value = [(doc_a,)]
                else:
                    result.all.return_value = [
                        _ChunkRow(uuid.uuid4(), doc_a, "全量内容", 1, 0.2),
                    ]
                self.calls += 1
                return result

        db = FakeDB()
        results = await rag_service.retrieve_similar(
            db=db,
            project_id=project_id,
            query_embedding=np.array([0.1, 0.2]),
        )
        assert len(results) == 1
        assert db.calls == 2  # 先查 Document 全量，再查 KbChunk

    @pytest.mark.asyncio
    async def test_doc_ids_empty_returns_empty(self) -> None:
        """doc_ids 为空列表时直接返回空，不执行任何查询（未挂载任何资料）."""
        db = MagicMock()
        results = await rag_service.retrieve_similar(
            db=db,
            project_id=uuid.uuid4(),
            query_embedding=np.array([0.1, 0.2]),
            doc_ids=[],
        )
        assert results == []
        db.execute.assert_not_called()


class TestRetrieveWithRerank:
    """retrieve_with_rerank — 向量召回(扩池) → rerank 精排 → 截断 top_k."""

    @pytest.mark.asyncio
    async def test_recall_expanded_and_rerank_applied(self, monkeypatch) -> None:
        """召回候选池放宽到 RERANK_RECALL_K，精排后截断到 top_k."""
        captured: dict = {}
        chunks = [
            ChunkResult(uuid.uuid4(), uuid.uuid4(), f"c{i}", 1, 0.9 - i * 0.1) for i in range(5)
        ]

        async def fake_retrieve(**kwargs):
            captured.update(kwargs)
            return chunks

        async def fake_rerank(query, candidates, *, top_n=None):
            captured["rerank_query"] = query
            captured["top_n"] = top_n
            # 模拟精排：倒序
            return list(reversed(candidates))[:top_n] if top_n else list(reversed(candidates))

        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)
        monkeypatch.setattr("app.services.rerank_service.rerank", fake_rerank)

        results = await rag_service.retrieve_with_rerank(
            db=MagicMock(),
            project_id=uuid.uuid4(),
            query="高可用架构",
            query_embedding=np.array([0.1, 0.2]),
            top_k=2,
        )
        # 召回池放宽
        assert captured["top_k"] == rag_service.RERANK_RECALL_K
        # 精排收到原查询与 top_n 截断参数
        assert captured["rerank_query"] == "高可用架构"
        assert captured["top_n"] == 2
        # 精排结果生效（倒序后取前 2）
        assert [c.content for c in results] == ["c4", "c3"]

    @pytest.mark.asyncio
    async def test_top_k_larger_than_recall_keeps_top_k(self, monkeypatch) -> None:
        """top_k 大于召回池时召回量不小于 top_k（不缩小召回）."""
        captured: dict = {}

        async def fake_retrieve(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)
        await rag_service.retrieve_with_rerank(
            db=MagicMock(),
            project_id=uuid.uuid4(),
            query="q",
            query_embedding=np.array([0.1]),
            top_k=50,
        )
        assert captured["top_k"] == 50


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

        async def fake_retrieve(
            db, project_id, query_embedding, top_k=20, threshold=0.3, doc_ids=None
        ):
            assert project_id == expected_project_id
            # 接入 rerank 后召回池放宽到 RERANK_RECALL_K，精排后截断到请求 top_k
            assert top_k == rag_service.RERANK_RECALL_K
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
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)

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

        async def fake_retrieve(
            db, project_id, query_embedding, top_k=20, threshold=0.3, doc_ids=None
        ):
            return []

        class FakeDB:
            def __init__(self) -> None:
                self.queries = 0

            async def execute(self, stmt):
                self.queries += 1
                raise AssertionError("无命中时不应再查询文档标题")

        monkeypatch.setattr(rag_service, "get_embedding", fake_embedding)
        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)

        items = await rag_service.search_materials(FakeDB(), uuid.uuid4(), "不存在的主题")
        assert items == []

    @pytest.mark.asyncio
    async def test_mock_mode_relaxes_threshold(self, monkeypatch) -> None:
        """mock 模式：伪向量相似度随机分布，阈值放宽到 -1 以免概率性零命中."""
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(
            db, project_id, query_embedding, top_k=20, threshold=0.3, doc_ids=None
        ):
            captured["threshold"] = threshold
            return []

        async def fake_is_mock(_mock=None):
            return True

        class FakeDB:
            async def execute(self, stmt):
                raise AssertionError("无命中时不应再查询文档标题")

        monkeypatch.setattr(rag_service, "get_embedding", fake_embedding)
        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", fake_is_mock)

        await rag_service.search_materials(FakeDB(), uuid.uuid4(), "任意查询")
        assert captured["threshold"] == -1.0

    @pytest.mark.asyncio
    async def test_real_mode_keeps_min_score(self, monkeypatch) -> None:
        """真实模式：阈值保持 min_score（默认 0，生产行为不变）."""
        captured: dict = {}

        async def fake_embedding(_text: str):
            return [0.1, 0.2]

        async def fake_retrieve(
            db, project_id, query_embedding, top_k=20, threshold=0.3, doc_ids=None
        ):
            captured["threshold"] = threshold
            return []

        class FakeDB:
            async def execute(self, stmt):
                raise AssertionError("无命中时不应再查询文档标题")

        monkeypatch.setattr(rag_service, "get_embedding", fake_embedding)
        monkeypatch.setattr(rag_service, "retrieve_similar", fake_retrieve)
        monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _fake_not_mock)

        await rag_service.search_materials(FakeDB(), uuid.uuid4(), "任意查询")
        assert captured["threshold"] == 0.0
