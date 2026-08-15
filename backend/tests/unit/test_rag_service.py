"""RAG 服务测试."""

from app.services.rag_service import chunk_text


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
