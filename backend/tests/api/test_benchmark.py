"""评分对标 API 测试 — 阶段 D（GET benchmark + PUT strategy）."""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.benchmark as benchmark_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import ScorePoint
from app.models.project import Project, ProjectMember

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _sp(clause_no: str = "1.1") -> ScorePoint:
    return ScorePoint(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=uuid.uuid4(),
        clause_no=clause_no,
        item="技术方案完整性",
        score=6.0,
        criteria="方案完整可行",
        is_star=False,
        strategy=None,
        risk_level=None,
        confirmed=True,
    )


@pytest.fixture
def override_db() -> Generator:
    def _override(scalar_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = [_result(s) for s in scalar_sequence]
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


class TestGetBenchmark:
    @pytest.mark.asyncio
    async def test_no_auth_401(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/benchmark")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_reads_sorted_items(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """项目成员读取对标表（懒计算，commit 回写 risk_level）."""
        session = override_db([_project(), _member_row()])
        items = [
            {
                "clause_no": "1",
                "item": "高分项",
                "score": 8.0,
                "criteria": "",
                "strategy": None,
                "risk": "high",
                "coverage": 0.2,
            },
            {
                "clause_no": "2",
                "item": "低分项",
                "score": 2.0,
                "criteria": "",
                "strategy": None,
                "risk": "low",
                "coverage": 0.8,
            },
        ]
        monkeypatch.setattr(
            benchmark_api.benchmark_service, "build_benchmark", AsyncMock(return_value=items)
        )
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/benchmark", headers=_headers(MEMBER_ID)
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == items
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_outsider_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/benchmark", headers=_headers(OTHER_ID)
        )
        assert resp.status_code == 403


class TestPutStrategy:
    @pytest.mark.asyncio
    async def test_owner_updates_strategy_with_audit(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """owner 编辑 strategy：落库 + 审计 benchmark.strategy + commit."""
        sp = _sp()
        session = override_db([_project(), sp])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action, kwargs))

        with patch.object(benchmark_api.audit, "record", fake_record):
            resp = await client.put(
                f"/api/v1/projects/{PROJECT_ID}/benchmark/1.1/strategy",
                json={"strategy": "补充历史案例与实施团队资质"},
                headers=_headers(OWNER_ID),
            )
        assert resp.status_code == 200
        assert sp.strategy == "补充历史案例与实施团队资质"
        assert recorded and recorded[0][1] == "benchmark.strategy"
        session.commit.assert_awaited()
        assert resp.json()["data"]["strategy"] == "补充历史案例与实施团队资质"

    @pytest.mark.asyncio
    async def test_non_owner_forbidden(self, client: AsyncClient, override_db) -> None:
        override_db([_project()])
        resp = await client.put(
            f"/api/v1/projects/{PROJECT_ID}/benchmark/1.1/strategy",
            json={"strategy": "x"},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_clause_4004(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.put(
            f"/api/v1/projects/{PROJECT_ID}/benchmark/9.9/strategy",
            json={"strategy": "x"},
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004
