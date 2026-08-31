"""节点共享辅助函数 — 常量/纯函数 + DB 操作委托 service 层（Phase 4 重构）.

Phase 4 变更：_update_workflow / _upsert_section / _persist_chapter_content
已迁入 service 层（workflow_metadata_service / chapter_service），此处保留
re-export 保持 monkeypatch 兼容（``_pkg._upsert_section`` 等调用不变）.

HITL 中断点：confirm_score_points / confirm_outline / review。
事务约定：async with async_session_factory() as db 退出仅 close 不 commit，
写块必须在退出前显式 await db.commit()，否则写入全部静默回滚。
"""

import logging
import uuid

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）

# Phase 4 re-exports — DB 操作委托 service 层
from app.services.infra.workflow_metadata_service import update_workflow as _update_workflow_impl  # noqa: F401
from app.services.proposal.chapter_service import (  # noqa: F401
    persist_chapter_content as _persist_chapter_content_impl,
    upsert_section as _upsert_section_impl,
)

# 日志名保持 app.agents.nodes（与拆包前完全一致）
logger = logging.getLogger("app.agents.nodes")

MIN_CHAPTER_LENGTH = 200  # 章节字数下限（validate 节点）
MAX_VALIDATE_RETRIES = 2  # 校验失败最大重试次数

# 三期 S4：section_token 节流参数（取先到者），避免 Redis 高频发布
STREAM_FLUSH_CHARS = 40  # 累积字符数上限
STREAM_FLUSH_SECS = 0.2  # 距上次发布间隔上限（秒）

# 资格/商务类需求关键词：招标原文提取（source=NULL）的需求中含资质/业绩/财务等
# 资格条件内容，不属于技术方案应答范围，大纲生成时排除（2026-08-25）
_QUALIFICATION_KEYWORDS = (
    "资质",
    "业绩",
    "财务",
    "信誉",
    "注册证书",
    "职称",
    "证书",
    "许可证",
    "保证金",
    "投标报价",
    "合同金额",
    # 人员资格类（负责人/工程师/建造师等岗位配置要求）
    "负责人",
    "工程师",
    "建造师",
    "项目总工",
    "项目经理",
    "人员配备",
    "组织机构",
    "岗位",
)


def _is_qualification_req(desc: str) -> bool:
    """判断技术需求是否为资格/商务/人员配置类（命中关键词）."""
    if not desc:
        return False
    return any(kw in desc for kw in _QUALIFICATION_KEYWORDS)


# ───────────────────────── DB 操作（委托 service 层） ─────────────────────────


async def _update_workflow(
    db,
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
    db,
    project_id: str,
    section_id: str,
    title: str,
    content_md: str,
    status: str = "draft",
    citations: list | None = None,
) -> None:
    """保存章节到 proposal_sections（委托 chapter_service）."""
    await _upsert_section_impl(
        db, project_id, section_id, title, content_md, status=status, citations=citations
    )


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
    """章节落库统一入口（委托 chapter_service）."""
    await _persist_chapter_content_impl(
        db,
        project_id,
        chapter_no,
        title,
        content,
        status=status,
        sections_tree=sections_tree,
        citations=citations,
    )
