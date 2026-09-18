"""节点共享辅助函数 — 常量/纯函数 + DB 操作委托 service 层（Phase 4 重构）.

Phase 4 变更：_update_workflow / _upsert_section / _persist_chapter_content
已迁入 service 层（workflow_metadata_service / chapter_service），此处保留
re-export 保持 monkeypatch 兼容（``_pkg._upsert_section`` 等调用不变）.
``_persist_chapter_content`` 的 upsert 经 ``_pkg._upsert_section`` 运行时查找，
保证 patch ``app.agents.nodes._upsert_section`` 的存量测试语义（2026-09-01 修复）.

HITL 中断点：confirm_score_points / confirm_outline / review。
事务约定：async with async_session_factory() as db 退出仅 close 不 commit，
写块必须在退出前显式 await db.commit()，否则写入全部静默回滚。
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）

# Phase 4 re-exports — DB 操作委托 service 层
from app.services.infra.workflow_metadata_service import (
    update_workflow as _update_workflow_impl,
)
from app.services.proposal.chapter_service import (
    split_chapter_to_sections,
)
from app.services.proposal.chapter_service import (
    upsert_section as _upsert_section_impl,
)

# 日志名保持 app.agents.nodes（与拆包前完全一致）
logger = logging.getLogger("app.agents.nodes")

MIN_CHAPTER_LENGTH = 200  # 章节字数下限（validate 节点）
MAX_VALIDATE_RETRIES = 2  # 校验失败最大重试次数

# 三期 S4：section_token 节流参数（取先到者），避免 Redis 高频发布
STREAM_FLUSH_CHARS = 40  # 累积字符数上限
STREAM_FLUSH_SECS = 0.2  # 距上次发布间隔上限（秒）


# ───────────────────────── DB 操作（委托 service 层） ─────────────────────────


async def _update_workflow(
    db: AsyncSession,
    project_id: str,
    *,
    phase: str | None = None,
    progress: float | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """创建或更新项目工作流元数据（委托 workflow_metadata_service）."""
    await _update_workflow_impl(
        db, project_id, phase=phase, progress=progress, status=status, error=error
    )


async def _upsert_section(
    db: AsyncSession,
    project_id: str,
    section_id: str,
    title: str,
    content_md: str,
    status: str = "draft",
    citations: list[Any] | None = None,
) -> None:
    """保存章节到 proposal_sections（委托 chapter_service）."""
    await _upsert_section_impl(
        db, project_id, section_id, title, content_md, status=status, citations=citations
    )


async def _persist_chapter_content(
    db: AsyncSession,
    project_id: str,
    chapter_no: str,
    title: str,
    content: str,
    status: str = "draft",
    sections_tree: list[Any] | None = None,
    citations: list[Any] | None = None,
) -> None:
    """章节落库统一入口：章级行 + 子节行.

    逻辑与 chapter_service.persist_chapter_content 一致，但 upsert 经
    ``_pkg._upsert_section`` 运行时查找——保持拆分前 monkeypatch 语义
    （assist_service 等调用方 patch ``app.agents.nodes._upsert_section`` 可拦截落库）.
    """
    await _pkg._upsert_section(
        db, project_id, chapter_no, title, content, status=status, citations=citations
    )
    for sec in split_chapter_to_sections(content, sections_tree or [], chapter_no):
        await _pkg._upsert_section(
            db, project_id, sec["section_id"], sec["title"], sec["content"], status=status
        )
