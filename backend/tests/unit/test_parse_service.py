"""招标解析服务测试."""

import io

import pytest

from app.core.exceptions import BizError
from app.services.parse_service import extract_tender_text


def _make_pdf_bytes(text: str = "Tender Document Sample Text") -> bytes:
    """构造最小合法 PDF（单页 + Helvetica 文本流，xref 偏移程序内计算）."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """用 python-docx 构造最小 DOCX bytes."""
    import docx

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


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

    @pytest.mark.asyncio
    async def test_pdf_extraction_with_real_bytes(self) -> None:
        """真实最小 PDF bytes 能解析出非空文本（回归：pdfplumber.open 位置传参）."""
        content = _make_pdf_bytes("Tender Document Sample Text")
        result = await extract_tender_text(content, "招标文件.pdf")
        assert result.strip(), "PDF 解析结果不应为空"
        assert "Tender Document Sample Text" in result

    @pytest.mark.asyncio
    async def test_docx_extraction_with_real_bytes(self) -> None:
        """真实最小 DOCX bytes 能解析出非空文本（回归：docx.Document 位置传参）."""
        content = _make_docx_bytes(["招标公告正文第一段", "技术要求清单第二段"])
        result = await extract_tender_text(content, "招标文件.docx")
        assert result.strip(), "DOCX 解析结果不应为空"
        assert "招标公告正文第一段" in result
        assert "技术要求清单第二段" in result
