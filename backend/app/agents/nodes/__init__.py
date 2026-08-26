"""LangGraph 节点函数 — 工作流各阶段实现（对齐 SDD §6）.

重构期 3：原单文件 nodes.py 按节点职责拆分为子模块——
parse（招标解析/评分点确认）、outline（大纲生成/确认）、
chapter（章节检索/撰写/校验）、review（一致性/整合/审阅/重写/导出/路由）、
_shared（共享常量与落库辅助）。本模块 re-export 全部原公开符号，
``from app.agents.nodes import xxx`` 与既有测试对包属性的 monkeypatch
（async_session_factory / publish_event / _upsert_section 等）语义不变：
节点实现统一经本包命名空间在调用时查找这些可 patch 名（子模块内记为 ``_pkg``）。

节点内通过 async_session_factory 打开 DB session（LangGraph 无 DI 注入）。
HITL 中断点：confirm_score_points / confirm_outline / review。

事务约定（BUG-2 修复）：``async with async_session_factory() as db`` 退出
仅 close 不 commit，写块必须在退出前显式 ``await db.commit()``，否则
proposal_skeletons / proposal_sections / reviews 等写入全部静默回滚。
只读块无需 commit（约定见 core.database.get_db docstring）。
"""

from app.agents.nodes._shared import (
    MAX_VALIDATE_RETRIES,
    MIN_CHAPTER_LENGTH,
    STREAM_FLUSH_CHARS,
    STREAM_FLUSH_SECS,
    _persist_chapter_content,
    _update_workflow,
    _upsert_section,
    logger,
)
from app.agents.nodes.chapter import retrieve_node, validate_node, write_node
from app.agents.nodes.outline import (
    _clear_outline_draft,
    _upsert_skeleton,
    confirm_outline_node,
    generate_outline_node,
)
from app.agents.nodes.parse import (
    _load_tender_context,
    confirm_score_points_node,
    parse_tender_node,
)
from app.agents.nodes.review import (
    _review_record,
    chapter_route,
    consistency_check_node,
    export_node,
    integrate_node,
    review_node,
    review_route,
    rewrite_node,
    route_after_confirm,
    route_after_outline_confirmed,
)
from app.agents.nodes.wait_division import wait_division_node
from app.core.database import async_session_factory
from app.services.infra import benchmark_service, kb_base_service, settings_service
from app.services.infra.event_service import publish_event

__all__ = [
    "MAX_VALIDATE_RETRIES",
    "MIN_CHAPTER_LENGTH",
    "STREAM_FLUSH_CHARS",
    "STREAM_FLUSH_SECS",
    "_clear_outline_draft",
    "_load_tender_context",
    "_persist_chapter_content",
    "_review_record",
    "_update_workflow",
    "_upsert_section",
    "_upsert_skeleton",
    "async_session_factory",
    "benchmark_service",
    "chapter_route",
    "confirm_outline_node",
    "confirm_score_points_node",
    "consistency_check_node",
    "export_node",
    "generate_outline_node",
    "integrate_node",
    "kb_base_service",
    "logger",
    "parse_tender_node",
    "publish_event",
    "retrieve_node",
    "review_node",
    "review_route",
    "rewrite_node",
    "route_after_confirm",
    "route_after_outline_confirmed",
    "settings_service",
    "validate_node",
    "wait_division_node",
    "write_node",
]
