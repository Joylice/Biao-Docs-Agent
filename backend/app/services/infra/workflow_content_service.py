"""工作流章节内容操作服务 — 人工编辑/分工回写/初稿生成/导出.

从 workflow_runtime.py 拆分（Phase 3 上帝模块治理），职责：
- save_section_edit: 人工编辑章节/子节直接落库
- sync_approved_chapter: 分工审核通过后回写正式方案
- generate_chapter_draft: LLM 生成章节初稿
- export_workflow: 导出 Word

依赖 workflow_runtime 的 get_state / update_state（单向）.
"""

import uuid

from app.core.exceptions import BizError
from app.core.sorting import natural_sort_key, numbered_sections


async def save_section_edit(
    db,
    project_id: uuid.UUID | str,
    chapter_no: str,
    content: str,
) -> None:
    """人工编辑章节/子节直接落库：state（chapters + 摘要重算）与 DB 同步.

    与 rewrite_chapter 的差异：不经 LLM，内容来自人工编辑；落库 status=review
    （对齐 write_node 的 _upsert_section 字段口径）。支持子节编号（如 1.1）：
    子节行更新后按自然序拼接同章子节行重建父章全文回写 state。
    章级编辑若大纲含嵌套子节则同步切分刷新子节行（子节真源一致）。
    DB 提交由 API 层统一 commit。
    """
    from sqlalchemy import select

    from app.agents.nodes import _persist_chapter_content, _upsert_section
    from app.models.proposal import ProposalSection
    from app.services.infra.workflow_runtime import get_state, update_state
    from app.services.proposal.chapter_service import extract_chapter_summary

    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    chapters = values.get("chapters", {})
    outline = values.get("outline", [])
    is_subsection = "." in chapter_no
    parent_no = chapter_no.rsplit(".", 1)[0] if is_subsection else chapter_no

    if is_subsection:
        if parent_no not in chapters:
            raise BizError(code=4004, message=f"章节 {parent_no} 尚未生成，无法保存子节")
        title = ""
        chapter = next((c for c in outline if str(c.get("chapter_no", "")) == parent_no), None)
        if chapter:
            title = next(
                (
                    t
                    for no, t in numbered_sections(chapter.get("sections", []) or [], parent_no)
                    if no == chapter_no
                ),
                "",
            )
        await _upsert_section(db, str(project_id), chapter_no, title, content, status="review")
        sec_result = await db.execute(
            select(ProposalSection).where(
                ProposalSection.project_id == uuid.UUID(str(project_id)),
                ProposalSection.section_id.startswith(f"{parent_no}."),
            )
        )
        sec_rows = sorted(sec_result.scalars().all(), key=lambda s: natural_sort_key(s.section_id))
        merged = "\n\n".join(s.content_md for s in sec_rows if s.content_md)
        target_no, target_content = parent_no, merged or content
    else:
        if chapter_no not in chapters:
            raise BizError(code=4004, message=f"章节 {chapter_no} 尚未生成，无法保存")
        target_no, target_content = chapter_no, content

    title = next((c.get("title", "") for c in outline if c.get("chapter_no") == target_no), "")
    if not title:
        title = (values.get("chapter_summaries", {}).get(target_no) or {}).get("title", "")

    summaries = dict(values.get("chapter_summaries", {}))
    summaries[target_no] = {"title": title, "summary": extract_chapter_summary(target_content)}
    await update_state(
        project_id,
        {"chapters": {target_no: target_content}, "chapter_summaries": summaries},
    )
    if not is_subsection:
        chapter = next((c for c in outline if c.get("chapter_no") == chapter_no), None)
        await _persist_chapter_content(
            db,
            str(project_id),
            chapter_no,
            title,
            content,
            status="review",
            sections_tree=(chapter or {}).get("sections", []),
        )


async def sync_approved_chapter(
    db,
    project_id: uuid.UUID | str,
    chapter_no: str,
    content: str,
    content_html: str | None = None,
) -> None:
    """分工审核通过后回写正式方案：state.chapters + proposal_sections + 摘要.

    与 save_section_edit 的差异：分工驱动模式下 chapters 初始为空，不要求章节已存在；
    内容来自分工人员编制（assignment.content，Markdown 与富文本双字段），
    落库 status=approved（区别于 write_node 的 draft / 人工编辑的 review）。
    支持子节编号：子节回写仅更新子节行，父章全文由同章子节行自然序拼接重建。
    DB 提交由 API 层统一 commit。
    """
    from sqlalchemy import select

    from app.agents.nodes import _persist_chapter_content, _upsert_section
    from app.models.proposal import ProposalSection
    from app.services.infra.workflow_runtime import get_state, update_state
    from app.services.proposal.chapter_service import extract_chapter_summary

    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    chapters = dict(values.get("chapters", {}))
    outline = values.get("outline", [])
    summaries = dict(values.get("chapter_summaries", {}))
    is_subsection = "." in chapter_no
    parent_no = chapter_no.rsplit(".", 1)[0] if is_subsection else chapter_no

    if is_subsection:
        title = ""
        chapter = next((c for c in outline if str(c.get("chapter_no", "")) == parent_no), None)
        if chapter:
            title = next(
                (
                    t
                    for no, t in numbered_sections(chapter.get("sections", []) or [], parent_no)
                    if no == chapter_no
                ),
                "",
            )
        await _upsert_section(
            db, str(project_id), chapter_no, title, content, status="approved"
        )
        sec_result = await db.execute(
            select(ProposalSection).where(
                ProposalSection.project_id == uuid.UUID(str(project_id)),
                ProposalSection.section_id.startswith(f"{parent_no}."),
            )
        )
        sec_rows = sorted(sec_result.scalars().all(), key=lambda s: natural_sort_key(s.section_id))
        merged = "\n\n".join(s.content_md for s in sec_rows if s.content_md)
        target_no, target_content = parent_no, merged or content
    else:
        target_no, target_content = chapter_no, content

    title = next((c.get("title", "") for c in outline if c.get("chapter_no") == target_no), "")
    if not title:
        title = (summaries.get(target_no) or {}).get("title", "")

    summaries[target_no] = {"title": title, "summary": extract_chapter_summary(target_content)}
    chapters[target_no] = target_content
    await update_state(
        project_id,
        {"chapters": chapters, "chapter_summaries": summaries},
    )
    if not is_subsection:
        chapter = next((c for c in outline if c.get("chapter_no") == chapter_no), None)
        await _persist_chapter_content(
            db,
            str(project_id),
            chapter_no,
            title,
            content,
            status="approved",
            sections_tree=(chapter or {}).get("sections", []),
        )
    else:
        await _persist_chapter_content(
            db,
            str(project_id),
            target_no,
            title,
            target_content,
            status="approved",
            sections_tree=(
                next((c for c in outline if c.get("chapter_no") == target_no), None) or {}
            ).get("sections", []),
        )


async def generate_chapter_draft(project_id: uuid.UUID | str, chapter_no: str) -> str:
    """分工编制：LLM 生成章节初稿并回写 state + proposal_sections（status=draft）.

    复用图内同一 generate_chapter 链路（RAG 检索 + 脱敏 + mock 降级）；
    与图内 write 节点的差异：不推进工作流阶段，仅产出初稿供人工编制。
    子节编号（如 1.1）：生成整章后切分，仅返回目标子节片段（AI 仍章级产出）。
    """
    from app.agents.nodes import _persist_chapter_content
    from app.core.database import async_session_factory
    from app.services.infra.kb_base_service import resolve_mount_doc_ids
    from app.services.infra.workflow_runtime import get_state, update_state
    from app.services.proposal.chapter_service import (
        extract_chapter_summary,
        generate_chapter,
        split_chapter_to_sections,
    )

    snapshot = await get_state(project_id)
    values = snapshot.values or {}
    outline = values.get("outline", [])
    is_subsection = "." in chapter_no
    target_no = chapter_no.rsplit(".", 1)[0] if is_subsection else chapter_no
    chapter = next((c for c in outline if str(c.get("chapter_no", "")) == target_no), None)
    if chapter is None:
        raise BizError(code=4004, message=f"章节 {chapter_no} 不在大纲中，无法生成初稿")

    async with async_session_factory() as db:
        doc_ids = await resolve_mount_doc_ids(
            db, values.get("mounted_kb_ids"), values.get("mounted_doc_ids")
        )

    content = await generate_chapter(
        chapter=chapter,
        score_points=values.get("score_points", []),
        tech_requirements=values.get("tech_requirements", []),
        project_id=uuid.UUID(str(project_id)),
        doc_ids=doc_ids,
    )
    if not content:
        raise BizError(code=5001, message="章节初稿生成失败：LLM 返回为空")

    title = chapter.get("title", "")
    summaries = dict(values.get("chapter_summaries", {}))
    summaries[target_no] = {"title": title, "summary": extract_chapter_summary(content)}
    await update_state(
        project_id,
        {"chapters": {target_no: content}, "chapter_summaries": summaries},
    )
    async with async_session_factory() as db:
        await _persist_chapter_content(
            db,
            str(project_id),
            target_no,
            title,
            content,
            status="draft",
            sections_tree=chapter.get("sections", []),
        )
        await db.commit()
    if is_subsection:
        for sec in split_chapter_to_sections(content, chapter.get("sections", []) or [], target_no):
            if sec["section_id"] == chapter_no:
                return sec["content"]
    return content


async def export_workflow(project_id: uuid.UUID | str) -> dict:
    """导出 Word — 复用图内 export 节点（export_to_word + 落库 + 事件），结果回写 state."""
    from app.agents.nodes import export_node
    from app.services.infra.workflow_runtime import get_state, update_state

    snapshot = await get_state(project_id)
    values = dict(snapshot.values or {})
    if not values.get("chapters"):
        raise BizError(code=4005, message="章节尚未生成，无法导出")

    values.setdefault("project_id", str(project_id))
    updates = await export_node(values)
    if updates.get("error"):
        raise BizError(code=5010, message=updates["error"])
    await update_state(project_id, updates)
    return {
        "export_status": updates.get("export_status", "done"),
        "export_storage_key": updates.get("export_storage_key", ""),
    }
