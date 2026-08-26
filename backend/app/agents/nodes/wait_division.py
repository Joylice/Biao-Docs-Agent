"""待分工节点 — wait_division（HITL，2026-08-25）.

由分工驱动编制模式：确认大纲后（start_generation=False）工作流停在此 interrupt，
等待项目负责人完成章节分工与编制审核后 resume 进入整合审阅。

resume 值：
- True / {"confirmed": True} → 继续进入 consistency_check → integrate → review
- 在 resume 前，分工审核通过的章节内容已经由 division API 回写 state.chapters
  （见 division_service.review_assignment → workflow_runtime.sync_approved_chapter）
"""


async def wait_division_node(state: dict) -> dict:
    """节点：HITL — 等待章节分工编制完成（由分工页驱动）."""
    from langgraph.types import interrupt

    decision = interrupt(
        {
            "type": "wait_division",
            "message": "大纲已确认，请在分工页完成章节编制后继续",
            "outline": state.get("outline", []),
        }
    )
    confirmed = decision is True or (
        isinstance(decision, dict) and decision.get("confirmed") is True
    )
    if not confirmed:
        return {"error": "分工编制未确认", "current_phase": "division"}
    return {
        "current_phase": "review",
        "progress": 0.85,
        "review_action": "",
        "review_feedback": {},
    }
