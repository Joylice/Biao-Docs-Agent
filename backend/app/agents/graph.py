"""LangGraph 工作流图构建 — 对齐 SDD §6.

流程：parse → confirm(HITL) → outline → confirm_outline(HITL)
      → start_generation=True: (retrieve → write → validate 循环) → consistency_check
      → integrate → auto_review(仅首轮) → review(HITL)
      → [approved: export / feedback: 回派负责人后等待复审（反馈不再重跑自动审阅）]
      → export → END
      → start_generation=False: wait_division(HITL) → [人工分工编制，审核通过回写后]
      → resume → consistency_check → integrate → review → ...

Checkpointer：生产用 AsyncPostgresSaver（thread_id = project_id）；测试用 InMemorySaver。
"""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.nodes import (
    auto_review_node,
    chapter_route,
    confirm_outline_node,
    confirm_score_points_node,
    consistency_check_node,
    export_node,
    generate_outline_node,
    integrate_node,
    parse_tender_node,
    refresh_context_node,
    retrieve_node,
    review_node,
    review_route,
    validate_node,
    wait_division_node,
    write_node,
)
from app.agents.state import BidState


def get_async_postgres_saver() -> type[Any]:
    """兼容导入 AsyncPostgresSaver.

    langgraph 1.2.11 内置的 langgraph.checkpoint.postgres 仅提供同步
    PostgresSaver；异步版本由 langgraph-checkpoint-postgres 的 aio 模块提供。

    以 `getattr` 动态取属性而非 `from ... import`：`AsyncPostgresSaver` 不在
    上游模块的显式导出名单内，直接 import 会被 mypy strict 的
    `no-implicit-reexport` 判为 attr-defined，但运行时确实可取到
    （workflow E2E 已覆盖该路径）。
    """
    from importlib import import_module

    for mod_name in (
        "langgraph.checkpoint.postgres",
        "langgraph.checkpoint.postgres.aio",
    ):
        mod = import_module(mod_name)
        saver_cls: type[Any] | None = getattr(mod, "AsyncPostgresSaver", None)
        if saver_cls is not None:
            return saver_cls
    raise ImportError("未找到 AsyncPostgresSaver：请确认已安装 langgraph-checkpoint-postgres")


def outline_route(state: dict[str, Any]) -> str:
    """confirm_outline 出口：
    - regenerate 标记 → 经 refresh_context 刷新源数据后回 generate_outline 重新生成
    - start_generation=False（分工驱动）→ 停靠 wait_division 待分工
    - 默认 → 进入章节生成循环（retrieve）
    """
    if state.get("regenerate_requested"):
        return "refresh_context"
    if state.get("current_phase") == "division":
        return "wait_division"
    return "retrieve"


def build_workflow() -> StateGraph[BidState]:
    """构建投标方案生成工作流图."""
    workflow = StateGraph(BidState)

    # 添加节点
    workflow.add_node("parse", parse_tender_node)
    workflow.add_node("confirm_score_points", confirm_score_points_node)
    workflow.add_node("refresh_context", refresh_context_node)
    workflow.add_node("generate_outline", generate_outline_node)
    workflow.add_node("confirm_outline", confirm_outline_node)
    workflow.add_node("wait_division", wait_division_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("write", write_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("consistency_check", consistency_check_node)
    workflow.add_node("integrate", integrate_node)
    workflow.add_node("auto_review", auto_review_node)
    workflow.add_node("review", review_node)
    workflow.add_node("export", export_node)

    # 入口
    workflow.add_edge(START, "parse")

    # parse → confirm(HITL) → outline
    workflow.add_edge("parse", "confirm_score_points")
    workflow.add_edge("confirm_score_points", "generate_outline")
    workflow.add_edge("generate_outline", "confirm_outline")

    # regenerate 路径：confirm_outline → refresh_context → generate_outline
    # → confirm_outline（循环，每次重新生成前刷新源数据）
    workflow.add_edge("refresh_context", "generate_outline")

    # confirm_outline → [regenerate: refresh_context → generate_outline 回边] /
    #                    [wait_division: 分工驱动停靠] / 章节循环
    workflow.add_conditional_edges(
        "confirm_outline",
        outline_route,
        {
            "refresh_context": "refresh_context",
            "wait_division": "wait_division",
            "retrieve": "retrieve",
        },
    )
    # wait_division（分工编制完成 resume）→ 整合校验 → 审阅
    # （分工内容已在审核通过时回写 state.chapters；不经过自动生成/自动重写链路，
    #   保持一致的人工编制内容）
    workflow.add_edge("wait_division", "integrate")
    workflow.add_edge("retrieve", "write")
    workflow.add_edge("write", "validate")
    workflow.add_conditional_edges(
        "validate",
        chapter_route,
        {
            "write": "write",  # 校验失败重试
            "retrieve": "retrieve",  # 生成下一章
            "consistency_check": "consistency_check",  # 全部完成 → 全文一致性检查
            "integrate": "integrate",  # 错误路径直达整合
        },
    )

    # consistency_check → integrate（检查不阻塞交付主链路）
    workflow.add_edge("consistency_check", "integrate")

    # integrate → auto_review（首次到达审阅阶段时跑一轮 AI 自动审阅）→ review(HITL)
    # 🔴 反馈回环 review_route → "review" **直接回 HITL、绕过 auto_review**
    #    ⇒ 自动审阅只在首轮跑，每轮反馈不再重复调用 LLM。
    workflow.add_edge("integrate", "auto_review")
    workflow.add_edge("auto_review", "review")

    # review → [approved: export / feedback: 回派负责人后等待复审 /
    #           redispatched: 意见全部回派，重新挂起等待复审]
    workflow.add_conditional_edges(
        "review",
        review_route,
        {
            "export": "export",
            "review": "review",
        },
    )

    # export → END
    workflow.add_edge("export", END)

    return workflow


def compile_workflow(checkpointer: Any = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """编译工作流（可选 attach checkpointer for persistence）."""
    graph = build_workflow()
    if checkpointer:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
