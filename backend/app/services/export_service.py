"""Word 文档导出服务."""

import io

from app.services.storage_service import upload_file


async def export_to_word(
    chapters: dict[str, str],
    outline: list[dict],
    project_name: str = "技术方案",
) -> str:
    """将章节内容导出为 Word 文档，返回 MinIO storage_key."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        from app.core.exceptions import BizError

        raise BizError(code=5010, message="python-docx 未安装") from None

    doc = Document()

    # 标题
    title = doc.add_heading(project_name, level=0)
    title.alignment = 1  # 居中

    # 按大纲顺序写入章节
    for chapter_info in outline:
        chapter_no = chapter_info.get("chapter_no", "")
        chapter_title = chapter_info.get("title", "")
        content = chapters.get(chapter_no, "")

        # 章节标题
        doc.add_heading(f"{chapter_no} {chapter_title}", level=1)

        # 章节内容（按段落拆分）
        for paragraph_text in content.split("\n\n"):
            if paragraph_text.strip():
                # 检查是否是子标题（以 ## 开头）
                stripped = paragraph_text.strip()
                if stripped.startswith("## "):
                    doc.add_heading(stripped[3:], level=2)
                elif stripped.startswith("### "):
                    doc.add_heading(stripped[4:], level=3)
                else:
                    para = doc.add_paragraph(stripped)
                    for run in para.runs:
                        run.font.size = Pt(12)

    # 保存到内存
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    # 上传到 MinIO
    filename = f"{project_name}.docx"
    storage_key = upload_file(
        file_content=buffer,
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    return storage_key
