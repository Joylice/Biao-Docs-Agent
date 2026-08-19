"""工作台 API 测试 — GET /workbench/summary（单端点双视图聚合）.

覆盖：
- 任务分桶计数与条目字段（项目名/章节号）
- 参与项目进度（approved/total → percent、状态分布）
- owner 名下项目纳入进度看板（含无分工项目）；待审核清单；非 owner 为空
- 未认证 401
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project
from app.models.proposal import ChapterAssignment, ProposalWorkflow

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


def _workflow(phase: str = "review") -> ProposalWorkflow:
    return ProposalWorkflow(project_id=PROJECT_ID, phase=phase)


@pytest.fixture
def override_db() -> Generator:
    def _override(side_effect: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = side_effect
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


class TestWorkbenchSummary:
    @pytest.mark.asyncio
    async def test_no_auth_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/workbench/summary")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_buckets_and_progress(self, client: AsyncClient, override_db) -> None:
        """分桶计数 + 项目进度百分比（approved/total）+ 阶段附注."""
        rows = [
            (_assignment("pending", "1.1"), "投标项目A"),
            (_assignment("in_progress", "1.2"), "投标项目A"),
            (_assignment("approved", "2"), "投标项目A"),
            (_assignment("rejected", "3"), "投标项目A"),
        ]
        override_db(
            [
                _join_result(rows),  # 我的分工 join
                _join_result([]),  # owner 名下项目（无）
                _scalars_result([_workflow("review")]),  # 项目阶段
                _join_result([]),  # owner 待审核（无）
            ]
        )
        resp = await client.get("/api/v1/workbench/summary", headers=_headers(USER_ID))
        assert resp.status_code == 200
        data = resp.json()["data"]
        tasks = data["tasks"]
        assert len(tasks["pending"]) == 1
        assert tasks["pending"][0]["chapter_no"] == "1.1"
        assert tasks["pending"][0]["project_name"] == "投标项目A"
        assert len(tasks["in_progress"]) == 1
        assert len(tasks["approved"]) == 1
        assert len(tasks["rejected"]) == 1
        assert len(tasks["submitted"]) == 0
        proj = data["my_projects"][0]
        assert proj["total"] == 4
        assert proj["approved"] == 1
        assert proj["percent"] == 25
        assert proj["phase"] == "review"
        assert proj["status_dist"]["pending"] == 1
        assert data["owner_review_pending"] == []

    @pytest.mark.asyncio
    async def test_owner_review_pending(self, client: AsyncClient, override_db) -> None:
        """owner 名下项目纳入进度看板；submitted 分工进入待审核清单."""
        submitted = _assignment("submitted", "2.1")
        owned = Project(id=PROJECT_ID, name="投标项目B", owner_id=USER_ID)
        override_db(
            [
                _join_result([]),  # 我的分工为空
                _join_result([(owned, submitted)]),  # owner 名下项目 LEFT JOIN 分工
                _scalars_result([]),  # 项目阶段（无工作流）
                _join_result([(submitted, "投标项目B")]),  # owner 待审核命中
            ]
        )
        resp = await client.get("/api/v1/workbench/summary", headers=_headers(USER_ID))
        assert resp.status_code == 200
        data = resp.json()["data"]
        # owner 名下项目即使本人无分工也出现在进度看板
        assert len(data["my_projects"]) == 1
        assert data["my_projects"][0]["project_name"] == "投标项目B"
        assert data["my_projects"][0]["total"] == 1
        assert data["my_projects"][0]["approved"] == 0
        pending = data["owner_review_pending"]
        assert len(pending) == 1
        assert pending[0]["chapter_no"] == "2.1"
        assert pending[0]["project_name"] == "投标项目B"

    @pytest.mark.asyncio
    async def test_empty_all(self, client: AsyncClient, override_db) -> None:
        """无任何分工：空分桶 + 空项目 + 空待审核（不报错）."""
        override_db([_join_result([]), _join_result([]), _join_result([])])
        resp = await client.get("/api/v1/workbench/summary", headers=_headers(USER_ID))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert all(v == [] for v in data["tasks"].values())
        assert data["my_projects"] == []
        assert data["owner_review_pending"] == []

    @pytest.mark.asyncio
    async def test_percent_rounding(self, client: AsyncClient, override_db) -> None:
        """进度百分比四舍五入（1/3 ≈ 33）."""
        rows = [
            (_assignment("approved", "1"), "项目C"),
            (_assignment("pending", "2"), "项目C"),
            (_assignment("pending", "3"), "项目C"),
        ]
        override_db([_join_result(rows), _join_result([]), _scalars_result([]), _join_result([])])
        resp = await client.get("/api/v1/workbench/summary", headers=_headers(USER_ID))
        proj = resp.json()["data"]["my_projects"][0]
        assert proj["percent"] == 33
        assert proj["phase"] == ""
