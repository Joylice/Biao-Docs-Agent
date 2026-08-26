"""节点共享辅助函数 — 工作流元数据与章节/子节落库（对齐 SDD §6）.

节点内通过 async_session_factory 打开 DB session（LangGraph 无 DI 注入）。
HITL 中断点：confirm_score_points / confirm_outline / review。

事务约定（BUG-2 修复）：``async with async_session_factory() as db`` 退出
仅 close 不 commit，写块必须在退出前显式 ``await db.commit()``，否则
proposal_skeletons / proposal_sections / reviews 等写入全部静默回滚。
只读块无需 commit（约定见 core.database.get_db docstring）。
"""

import logging
import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.models.proposal import ProposalSection, ProposalWorkflow

# 日志名保持 app.agents.nodes（与拆包前完全一致）
logger = logging.getLogger("app.agents.nodes")

MIN_CHAPTER_LENGTH = 200  # 章节字数下限（validate 节点）
MAX_VALIDATE_RETRIES = 2  # 校验失败最大重试次数

# 三期 S4：section_token 节流参数（取先到者），避免 Redis 高频发布
STREAM_FLUSH_CHARS = 40  # 累积字符数上限
STREAM_FLUSH_SECS = 0.2  # 距上次发布间隔上限（秒）


# ───────────────────────── 内部工具 ─────────────────────────


async def _update_workflow(
    db,
    project_id: str,
    *,
    phase: str | None = None,
    progress: float | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """创建或更新项目工作流元数据."""
    result = await db.execute(
        select(ProposalWorkflow).where(ProposalWorkflow.project_id == uuid.UUID(project_id))
    )
    wf = result.scalar_one_or_none()
    if not wf:
        wf = ProposalWorkflow(project_id=uuid.UUID(project_id), thread_id=str(project_id))
        db.add(wf)
    if phase is not None:
        wf.phase = phase
    if progress is not None:
        wf.progress = progress
    if status is not None:
        wf.status = status
    if error is not None:
        wf.error = error
    await db.flush()


async def _upsert_section(
    db,
    project_id: str,
    section_id: str,
    title: str,
    content_md: str,
    status: str = "draft",
    citations: list | None = None,
) -> None:
    """保存章节到 proposal_sections（upsert）；citations 为阶段 E3 引用溯源元数据."""
    result = await db.execute(
        select(ProposalSection).where(
            ProposalSection.project_id == uuid.UUID(project_id),
            ProposalSection.section_id == section_id,
        )
    )
    section = result.scalar_one_or_none()
    if not section:
        section = ProposalSection(
            project_id=uuid.UUID(project_id),
            section_id=section_id,
            title=title,
            content_md=content_md,
            status=status,
        )
        if citations is not None:
            section.citations = citations
        db.add(section)
    else:
        section.title = title
        section.content_md = content_md
        section.status = status
        if citations is not None:
            section.citations = citations
    await db.flush()


async def _persist_chapter_content(
    db,
    project_id: str,
    chapter_no: str,
    title: str,
    content: str,
    status: str = "draft",
    sections_tree: list | None = None,
    citations: list | None = None,
) -> None:
    """章节落库统一入口：章级行（全文）+ 嵌套大纲时切分子节行.

    state.chapters 保持章级全文（检索/摘要用），proposal_sections 子节行为
    子节真源（子节分工/编辑粒度）；string[] 大纲仅写章级行（向后兼容）。
    citations（阶段 E3）：检索命中溯源元数据，写章级行供导出标注。
    """
    from app.services.proposal.chapter_service import split_chapter_to_sections

    await _pkg._upsert_section(
        db, project_id, chapter_no, title, content, status=status, citations=citations
    )
    for sec in split_chapter_to_sections(content, sections_tree or [], chapter_no):
        await _pkg._upsert_section(
            db, project_id, sec["section_id"], sec["title"], sec["content"], status=status
        )
