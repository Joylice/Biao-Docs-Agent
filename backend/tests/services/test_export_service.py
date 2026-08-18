"""export_service 单元测试 — 格式要求驱动 Word 排版.

覆盖：默认样式（正文 12pt）、格式要求应用（字体/字号/行距/页边距/标题字号），
通过捕获上传 buffer 重新打开 docx 断言。
"""

import base64
import io

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

import app.services.export_service as export_service
from app.core.exceptions import BizError

OUTLINE = [{"chapter_no": "1", "title": "项目概述"}]
CHAPTERS = {"1": "## 背景\n\n这是正文段落内容，用于断言排版属性。"}

# 1x1 合法 PNG（内嵌断言用）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def capture_upload(monkeypatch):
    """拦截 MinIO 上传，返回捕获的 buffer 容器."""
    captured: dict = {}

    def fake_upload(file_content, filename, content_type):
        captured["buffer"] = file_content
        captured["filename"] = filename
        return "test/export.docx"

    monkeypatch.setattr(export_service, "upload_file", fake_upload)
    return captured


def _open(captured: dict) -> Document:
    buffer: io.BytesIO = captured["buffer"]
    buffer.seek(0)
    return Document(buffer)


def _body_paragraph(doc: Document):
    """取正文段落（Normal 样式，排除标题/Title）."""
    return next(p for p in doc.paragraphs if p.style.name == "Normal")


class TestDefaultStyle:
    @pytest.mark.asyncio
    async def test_export_defaults_without_requirements(self, capture_upload) -> None:
        """无格式要求：正文 12pt、行距 1.5 倍、默认页边距."""
        await export_service.export_to_word(CHAPTERS, OUTLINE, "测试项目")
        doc = _open(capture_upload)
        para = _body_paragraph(doc)
        assert para.runs[0].font.size == Pt(12)
        assert para.paragraph_format.line_spacing == 1.5


class TestFormatApplied:
    @pytest.mark.asyncio
    async def test_export_applies_format_requirements(self, capture_upload) -> None:
        """格式要求应用：宋体四号正文、三号章标题、固定行距、页边距."""
        fr = [
            {"category": "font_body", "requirement": "正文宋体四号"},
            {"category": "font_heading", "requirement": "章标题三号"},
            {"category": "line_spacing", "requirement": "固定值28磅"},
            {"category": "margin", "requirement": "上下2.54cm，左右3.17cm"},
        ]
        await export_service.export_to_word(CHAPTERS, OUTLINE, "测试项目", fr)
        doc = _open(capture_upload)

        # 正文字体/字号（含 eastAsia 中文字体）
        para = _body_paragraph(doc)
        run = para.runs[0]
        assert run.font.size == Pt(14)
        assert run.font.name == "宋体"
        assert run._element.rPr.rFonts.get(qn("w:eastAsia")) == "宋体"

        # 固定行距
        assert para.paragraph_format.line_spacing == Pt(28)

        # 一级章节标题字号
        h1 = next(p for p in doc.paragraphs if p.style.name == "Heading 1")
        assert h1.runs[0].font.size == Pt(16)

        # 页边距（docx 以 twip 存储，按 twip 粒度断言）
        section = doc.sections[0]
        assert section.top_margin == Twips(1440)
        assert section.bottom_margin == Twips(1440)
        assert section.left_margin == Twips(1797)
        assert section.right_margin == Twips(1797)

    @pytest.mark.asyncio
    async def test_export_unparsable_requirements_fallback(self, capture_upload) -> None:
        """不可解析的格式要求回退默认样式，不阻塞导出."""
        fr = [{"category": "font_body", "requirement": "排版美观"}]
        key = await export_service.export_to_word(CHAPTERS, OUTLINE, "测试项目", fr)
        assert key == "test/export.docx"
        doc = _open(capture_upload)
        assert _body_paragraph(doc).runs[0].font.size == Pt(12)


class TestImageEmbed:
    """Markdown 图片语法内嵌 Word（阶段 3）."""

    @pytest.mark.asyncio
    async def test_image_embedded_from_signed_url(self, capture_upload, monkeypatch) -> None:
        """签名 URL → 提取 storage_key 拉取字节 → inline shape 内嵌."""
        downloaded: list[str] = []

        def fake_download(key: str) -> bytes:
            downloaded.append(key)
            return PNG_1PX

        monkeypatch.setattr(export_service, "download_file", fake_download)
        url = "http://minio:9000/bid-documents/images/pid/u1/arch.png?X-Amz-Signature=abc"
        chapters = {"1": f"架构示意如下\n\n![架构图]({url})\n\n结尾段落"}
        await export_service.export_to_word(chapters, OUTLINE, "测试项目")
        assert downloaded == ["images/pid/u1/arch.png"]
        doc = _open(capture_upload)
        assert len(doc.inline_shapes) == 1

    @pytest.mark.asyncio
    async def test_image_fetch_failure_fallback_text(self, capture_upload, monkeypatch) -> None:
        """拉取失败降级为文本说明，不阻塞导出."""

        def fake_download(key: str) -> bytes:
            raise BizError(code=5003, message="下载失败")

        monkeypatch.setattr(export_service, "download_file", fake_download)
        chapters = {"1": "![架构图](images/pid/u1/arch.png)"}
        key = await export_service.export_to_word(chapters, OUTLINE, "测试项目")
        assert key == "test/export.docx"
        doc = _open(capture_upload)
        assert len(doc.inline_shapes) == 0
        texts = [p.text for p in doc.paragraphs]
        assert any("[图片: 架构图]" in t for t in texts)

