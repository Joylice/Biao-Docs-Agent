"""workbench_service 单元测试 — 工作台双视图聚合（批次 1b 自 api/workbench.py 下沉）.

覆盖行为等价：
- 任务分桶计数与条目字段（项目名/章节号）
- 参与项目进度 percent/status_dist/phase 附注
- owner 视图：名下项目（含无分工 total=0）纳入看板；待审核清单
- 无项目时跳过阶段查询（execute 次数 3）
- 只读不 commit（事务提交保留在 api 层）
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.project import Project
from app.models.proposal import ChapterAssignment, ProposalWorkflow
from app.services import workbench_service

USER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _join_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _assignment(status: str, chapter_no: str = "1") -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no=chapter_no,
        title=f"章节 {chapter_no}",
        assignee_id=USER_ID,
        assigned_by=uuid.uuid4(),
        status=status,
    )


def _session(side_effect: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = side_effect
    return session


class TestGetSummary:
    async def test_buckets_progress_and_phase(self) -> None:
        """分桶计数 + 进度百分比 + 阶段附注；非 owner 待审核为空."""
        rows = [
            (_assignment("pending", "1.1"), "投标项目A"),
            (_assignment("in_progress", "1.2"), "投标项目A"),
            (_assignment("approved", "2"), "投标项目A"),
            (_assignment("rejected", "3"), "投标项目A"),
        ]
        session = _session(
            [
                _join_result(rows),
                _join_result([]),
                _scalars_result([ProposalWorkflow(project_id=PROJECT_ID, phase="review")]),
                _join_result([]),
            ]
        )
        data = await workbench_service.get_summary(session, USER_ID)
        tasks = data["tasks"]
        assert len(tasks["pending"]) == 1
        assert tasks["pending"][0]["chapter_no"] == "1.1"
        assert tasks["pending"][0]["project_name"] == "投标项目A"
        assert len(tasks["in_progress"]) == 1
        assert len(tasks["approved"]) == 1
        assert len(tasks["rejected"]) == 1
        assert tasks["submitted"] == []
        proj = data["my_projects"][0]
        assert proj["total"] == 4
        assert proj["approved"] == 1
        assert proj["percent"] == 25
        assert proj["phase"] == "review"
        assert proj["status_dist"]["pending"] == 1
        assert data["owner_review_pending"] == []

    async def test_owner_view_includes_unassigned_projects(self) -> None:
        """owner 名下项目纳入进度看板；submitted 分工进入待审核清单."""
        submitted = _assignment("submitted", "2.1")
        owned = Project(id=PROJECT_ID, name="投标项目B", owner_id=USER_ID)
        session = _session(
            [
                _join_result([]),
                _join_result([(owned, submitted)]),
                _scalars_result([]),
                _join_result([(submitted, "投标项目B")]),
            ]
        )
        data = await workbench_service.get_summary(session, USER_ID)
        assert len(data["my_projects"]) == 1
        assert data["my_projects"][0]["project_name"] == "投标项目B"
        assert data["my_projects"][0]["total"] == 1
        assert data["my_projects"][0]["approved"] == 0
        pending = data["owner_review_pending"]
        assert len(pending) == 1
        assert pending[0]["chapter_no"] == "2.1"
        assert pending[0]["project_name"] == "投标项目B"

    async def test_skips_phase_query_when_no_projects(self) -> None:
        """无任何项目聚合行时跳过 proposal_workflows 查询（execute 仅 3 次）."""
        session = _session([_join_result([]), _join_result([]), _join_result([])])
        data = await workbench_service.get_summary(session, USER_ID)
        assert all(v == [] for v in data["tasks"].values())
        assert data["my_projects"] == []
        assert data["owner_review_pending"] == []
        assert session.execute.await_count == 3

    async def test_percent_rounding(self) -> None:
        """进度百分比四舍五入（1/3 ≈ 33），无工作流行 phase 空串."""
        rows = [
            (_assignment("approved", "1"), "项目C"),
            (_assignment("pending", "2"), "项目C"),
            (_assignment("pending", "3"), "项目C"),
        ]
        session = _session(
            [_join_result(rows), _join_result([]), _scalars_result([]), _join_result([])]
        )
        data = await workbench_service.get_summary(session, USER_ID)
        proj = data["my_projects"][0]
        assert proj["percent"] == 33
        assert proj["phase"] == ""

    async def test_does_not_commit(self) -> None:
        """只读聚合：service 不 commit（事务提交保留在 api 层）."""
        session = _session([_join_result([]), _join_result([]), _join_result([])])
        await workbench_service.get_summary(session, USER_ID)
        session.commit.assert_not_awaited()
