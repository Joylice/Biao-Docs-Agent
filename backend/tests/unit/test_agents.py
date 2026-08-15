"""LangGraph 状态与节点测试."""

from app.agents.state import TenderState


class TestTenderState:
    """TenderState 测试."""

    def test_default_state(self) -> None:
        """默认状态初始化."""
        state = TenderState()
        assert state.project_id == ""
        assert state.current_phase == "init"
        assert state.score_points == []
        assert state.chapters == {}
        assert state.progress == 0.0

    def test_to_dict(self) -> None:
        """状态转字典."""
        state = TenderState(project_id="test-123", current_phase="parse")
        d = state.to_dict()
        assert d["project_id"] == "test-123"
        assert d["current_phase"] == "parse"
        assert "score_points" in d

    def test_from_dict(self) -> None:
        """从字典恢复状态."""
        data = {
            "project_id": "abc",
            "user_id": "def",
            "current_phase": "generate",
            "progress": 0.5,
            "chapters": {"1": "content"},
        }
        state = TenderState.from_dict(data)
        assert state.project_id == "abc"
        assert state.current_phase == "generate"
        assert state.chapters == {"1": "content"}

    def test_from_dict_ignores_extra_keys(self) -> None:
        """从字典恢复时忽略未知字段."""
        data = {"project_id": "abc", "unknown_field": "ignored"}
        state = TenderState.from_dict(data)
        assert state.project_id == "abc"
        assert not hasattr(state, "unknown_field")


class TestWorkflowNodes:
    """工作流节点函数测试."""

    def test_route_after_confirm_confirmed(self) -> None:
        """确认后路由到大纲生成."""
        from app.agents.nodes import route_after_confirm

        state = {"score_points_confirmed": True}
        assert route_after_confirm(state) == "generate_outline"

    def test_route_after_confirm_not_confirmed(self) -> None:
        """未确认时回到确认."""
        from app.agents.nodes import route_after_confirm

        state = {"score_points_confirmed": False}
        assert route_after_confirm(state) == "confirm"

    def test_route_after_outline_confirmed(self) -> None:
        """大纲确认后路由到章节生成."""
        from app.agents.nodes import route_after_outline_confirmed

        state = {"outline_confirmed": True}
        assert route_after_outline_confirmed(state) == "generate_chapter"

    def test_route_after_outline_not_confirmed(self) -> None:
        """大纲未确认时回到确认."""
        from app.agents.nodes import route_after_outline_confirmed

        state = {"outline_confirmed": False}
        assert route_after_outline_confirmed(state) == "confirm_outline"
