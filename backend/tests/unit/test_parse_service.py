"""招标解析服务测试."""

import pytest

from app.core.exceptions import BizError
from app.services.parse_service import extract_tender_text


class TestExtractTenderText:
    """文本提取测试."""

    @pytest.mark.asyncio
    async def test_txt_extraction(self) -> None:
        """TXT 文件直接解码."""
        content = "测试文本内容".encode()
        result = await extract_tender_text(content, "test.txt")
        assert "测试文本内容" in result

    @pytest.mark.asyncio
    async def test_unsupported_format_raises(self) -> None:
        """不支持的格式抛出 BizError."""
        with pytest.raises(BizError, match=r"不支持的文件格式"):
            await extract_tender_text(b"fake content", "test.xyz")

    @pytest.mark.asyncio
    async def test_pdf_without_library(self) -> None:
        """PDF 解析在无库时抛出明确错误."""
        try:
            import pdfplumber  # noqa: F401

            pytest.skip("pdfplumber 已安装，无法测试缺失场景")
        except ImportError:
            with pytest.raises(BizError, match=r"pdfplumber 未安装|PDF 解析失败"):
                await extract_tender_text(b"fake pdf", "test.pdf")

    @pytest.mark.asyncio
    async def test_docx_without_library(self) -> None:
        """Word 解析在无库时抛出明确错误."""
        try:
            import docx  # noqa: F401

            pytest.skip("python-docx 已安装，无法测试缺失场景")
        except ImportError:
            with pytest.raises(BizError, match=r"python-docx 未安装|Word 解析失败"):
                await extract_tender_text(b"fake docx", "test.docx")
