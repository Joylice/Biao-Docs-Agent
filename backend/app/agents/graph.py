"""LangGraph 工作流图构建 — 对齐 SDD §6.

流程：parse → confirm(HITL) → outline → confirm_outline(HITL)
      → start_generation=True: (retrieve → write → validate 循环) → consistency_check
      → integrate → review(HITL) → [approved: export / feedback: rewrite → integrate → review]
      → export → END
      → start_generation=False: wait_division(HITL) → [人工分工编制，审核通过回写后]
      → resume → consistency_check → integrate → review → ...

Checkpointer：生产用 AsyncPostgresSaver（thread_id = project_id）；测试用 InMemorySaver。
"""

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
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
    rewrite_node,
    validate_node,
    wait_division_node,
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


def build_workflow() -> StateGraph:
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
    workflow.add_node("review", review_node)
    workflow.add_node("rewrite", rewrite_node)
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

    # integrate → review(HITL)
    workflow.add_edge("integrate", "review")

    # review → [approved: export / feedback: rewrite → integrate → review /
    # redispatched: 意见全部回派负责人，重新挂起等待复审]
    workflow.add_conditional_edges(
        "review",
        review_route,
        {
            "export": "export",
            "rewrite": "rewrite",
            "review": "review",
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
