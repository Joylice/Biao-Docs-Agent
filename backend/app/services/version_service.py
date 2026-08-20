"""方案版本库服务 — 快照 Word + Markdown 源（版本续号）与自动触发判定."""

import io
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.document import Document
from app.models.proposal import ChapterAssignment, ProposalSection, ProposalVersion
from app.services import workflow_runtime
from app.services.export_service import export_to_word
from app.services.storage_service import upload_file

logger = logging.getLogger(__name__)

# 自动快照触发：禁止存在的编制中状态集合（有任一即不满足「全部定稿」）
_BLOCKING_STATUSES = frozenset({"pending", "in_progress", "submitted"})


def build_markdown_source(
    project_name: str, outline: list[dict], chapters: dict[str, str]
) -> str:
    """按大纲结构拼装 Markdown 源（章标题 + 子节列表 + 正文）."""
    lines: list[str] = [f"# {project_name}", ""]
    for c in outline:
        no = str(c.get("chapter_no", ""))
        title = str(c.get("title", ""))
        lines.append(f"## {no} {title}".strip())
        for s in c.get("sections", []) or []:
            lines.append(f"### {s}")
        content = (chapters.get(no) or "").strip()
        if content:
            lines.append("")
            lines.append(content)
        lines.append("")
    # outline 缺失时兜底：仅按 chapters 顺序输出
    if not outline:
        for no, content in chapters.items():
            lines.append(f"## {no}")
            lines.append("")
            lines.append((content or "").strip())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def _latest_format_requirements(db: AsyncSession, project_id: uuid.UUID):
    """读取最新招标文件的格式要求（best effort，失败/无则 None 回退默认排版）."""
    try:
        result = await db.execute(
            select(Document)
            .where(
                Document.project_id == project_id,
                Document.doc_type == "tender_file",
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        tender = result.scalar_one_or_none()
        if tender:
            return (tender.meta or {}).get("format_requirements")
    except Exception:
        logger.exception("版本快照读取格式要求失败，使用默认排版")
    return None


async def create_snapshot(
    db: AsyncSession,
    project_id: uuid.UUID,
    project_name: str,
    user_id: uuid.UUID | None = None,
    snapshot_note: str | None = None,
) -> ProposalVersion:
    """创建版本快照：导出 Word + Markdown 源打包入 MinIO，version 续号.

    user_id=None 表示自动快照（全章审核通过触发）。
    """
    snapshot = await workflow_runtime.get_state(project_id)
    values = (snapshot.values or {}) if snapshot else {}
    chapters: dict[str, str] = values.get("chapters", {}) or {}
    outline: list[dict] = values.get("outline", []) or []
    name = values.get("project_name") or project_name
    if not chapters:
        raise ValidationError("方案内容尚未生成，无法创建版本快照")

    # version 续号（UNIQUE(project_id, version) 兜底并发冲突）
    result = await db.execute(
        select(func.coalesce(func.max(ProposalVersion.version), 0)).where(
            ProposalVersion.project_id == project_id
        )
    )
    version = int(result.scalar() or 0) + 1

    format_requirements = await _latest_format_requirements(db, project_id)
    storage_key_docx = await export_to_word(
        chapters=chapters,
        outline=outline,
        project_name=name,
        format_requirements=format_requirements,
    )

    md_text = build_markdown_source(name, outline, chapters)
    storage_key_source = upload_file(
        io.BytesIO(md_text.encode("utf-8")),
        filename=f"proposal-v{version}.md",
        content_type="text/markdown",
        key_prefix=f"versions/{project_id}",
    )

    record = ProposalVersion(
        project_id=project_id,
        version=version,
        snapshot_note=(snapshot_note or "").strip() or None,
        storage_key_docx=storage_key_docx,
        storage_key_source=storage_key_source,
        created_by=user_id,
        # 阶段 E5：结构化快照（回滚数据源；旧版本无此字段不可回滚）
        snapshot_json={"outline": outline, "chapters": chapters},
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def rollback_version(
    db: AsyncSession, project_id: uuid.UUID, version: ProposalVersion
) -> int:
    """版本回滚：snapshot_json → 回写 proposal_sections 章级行 + 同步图状态.

    回写后章状态置 draft（需重新审阅）；章节行缺失时按大纲标题新建。
    返回恢复的章节数；无结构化快照抛 ValidationError。
    """
    data = version.snapshot_json or {}
    chapters: dict[str, str] = data.get("chapters") or {}
    outline: list[dict] = data.get("outline") or []
    if not chapters:
        raise ValidationError("该版本无结构化快照，无法回滚（仅支持 E5 后创建的版本）")

    titles = {str(c.get("chapter_no", "")): str(c.get("title", "")) for c in outline}
    for chapter_no, content in chapters.items():
        chapter_no = str(chapter_no)
        result = await db.execute(
            select(ProposalSection).where(
                ProposalSection.project_id == project_id,
                ProposalSection.section_id == chapter_no,
            )
        )
        section = result.scalar_one_or_none()
        if section is not None:
            section.content_md = content
            section.status = "draft"
        else:
            db.add(
                ProposalSection(
                    project_id=project_id,
                    section_id=chapter_no,
                    title=titles.get(chapter_no, chapter_no),
                    content_md=content,
                    status="draft",
                )
            )

    # 图状态同步（ReviewView/生成页即时可见回滚后正文）
    await workflow_runtime.update_state(project_id, {"chapters": chapters, "outline": outline})
    return len(chapters)


async def maybe_auto_snapshot(
    db: AsyncSession, project_id: uuid.UUID, project_name: str
) -> ProposalVersion | None:
    """自动快照判定：无 pending/in_progress/submitted 且至少 1 章 approved.

    分工审核通过后调用；不满足条件或快照失败均不阻塞审核主流程。
    """
    result = await db.execute(
        select(ChapterAssignment.status).where(ChapterAssignment.project_id == project_id)
    )
    statuses = [row[0] for row in result.all()]
    if not statuses:
        return None
    if any(s in _BLOCKING_STATUSES for s in statuses):
        return None
    if not any(s == "approved" for s in statuses):
        return None
    try:
        record = await create_snapshot(
            db,
            project_id,
            project_name,
            user_id=None,
            snapshot_note="自动快照：全部章节审核通过",
        )
        await db.commit()
        return record
    except Exception:
        logger.exception("自动版本快照失败（不阻塞审核）")
        await db.rollback()
        return None
