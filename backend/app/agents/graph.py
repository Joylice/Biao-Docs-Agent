"""LangGraph 工作流图构建 — 对齐 SDD §6.

流程：parse → confirm(HITL) → outline → confirm_outline(HITL)
      → (retrieve → write → validate 循环) → integrate → review(HITL)
      → [approved: export / feedback: rewrite → integrate → review]
      → export → END

Checkpointer：生产用 AsyncPostgresSaver（thread_id = project_id）；测试用 InMemorySaver。
"""

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    chapter_route,
    confirm_outline_node,
    confirm_score_points_node,
    export_node,
    generate_outline_node,
    integrate_node,
    parse_tender_node,
    retrieve_node,
    review_node,
    review_route,
    rewrite_node,
    validate_node,
    write_node,
)
from app.agents.state import BidState


def get_async_postgres_saver():
    """兼容导入 AsyncPostgresSaver.

    langgraph 1.2.11 内置的 langgraph.checkpoint.postgres 仅提供同步
    PostgresSaver；异步版本由 langgraph-checkpoint-postgres 的 aio 模块提供。
    """
    try:
        from langgraph.checkpoint.postgres import AsyncPostgresSaver
    except ImportError:  # pragma: no cover - 依赖包命名空间差异
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    return AsyncPostgresSaver


def outline_route(state: dict) -> str:
    """confirm_outline 出口：regenerate 标记 → 回 generate_outline 重新生成；否则进入章节循环."""
    return "generate_outline" if state.get("regenerate_requested") else "retrieve"


def build_workflow() -> StateGraph:
    """构建投标方案生成工作流图."""
    workflow = StateGraph(BidState)

    # 添加节点
    workflow.add_node("parse", parse_tender_node)
    workflow.add_node("confirm_score_points", confirm_score_points_node)
    workflow.add_node("generate_outline", generate_outline_node)
    workflow.add_node("confirm_outline", confirm_outline_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("write", write_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("integrate", integrate_node)
    workflow.add_node("review", review_node)
    workflow.add_node("rewrite", rewrite_node)
    workflow.add_node("export", export_node)

    # 入口
    workflow.add_edge(START, "parse")

    # parse → confirm(HITL) → outline
    workflow.add_edge("parse", "confirm_score_points")
    workflow.add_edge("confirm_score_points", "generate_outline")
    workflow.add_edge("generate_outline", "confirm_outline")

    # confirm_outline → [regenerate: generate_outline → confirm_outline 回边] / 章节循环
    workflow.add_conditional_edges(
        "confirm_outline",
        outline_route,
        {"generate_outline": "generate_outline", "retrieve": "retrieve"},
    )
    workflow.add_edge("retrieve", "write")
    workflow.add_edge("write", "validate")
    workflow.add_conditional_edges(
        "validate",
        chapter_route,
        {
            "write": "write",  # 校验失败重试
            "retrieve": "retrieve",  # 生成下一章
            "integrate": "integrate",  # 全部完成
        },
    )

    # integrate → review(HITL)
    workflow.add_edge("integrate", "review")

    # review → [approved: export / feedback: rewrite → integrate → review]
    workflow.add_conditional_edges(
        "review",
        review_route,
        {
            "export": "export",
            "rewrite": "rewrite",
        },
    )
    workflow.add_edge("rewrite", "integrate")

    # export → END
    workflow.add_edge("export", END)

    return workflow


def compile_workflow(checkpointer=None):
    """编译工作流（可选 attach checkpointer for persistence）."""
    graph = build_workflow()
    if checkpointer:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
