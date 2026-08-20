"""废标条款 API 测试 — GET/PUT disqualification-clauses + risks + 导出门禁（阶段 H）.

覆盖：
- GET：成员读取条款列表、非成员 403、文档不存在 404
- PUT：幂等覆盖（删旧插新）+ 审计 + 显式 commit、条目清洗（缺 title 丢弃/非法枚举归一）
- GET 项目级汇总：聚合返回
- GET disqualification-risks：章节命中扫描映射
- 导出门禁：存在未确认 high 条款 → 4012 阻塞；全部确认后放行
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.documents as documents_api
import app.api.workflow as workflow_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import DisqualificationClause, Document
from app.models.project import Project

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _tender_doc() -> Document:
    return Document(
        id=DOC_ID,
        project_id=PROJECT_ID,
        doc_type="tender_file",
        title="招标文件.docx",
        storage_key="k",
        status="parsed",
    )


def _clause(**kwargs) -> DisqualificationClause:
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=DOC_ID,
        clause_no="2.1",
        title="资质要求",
        risk_category="qualification_missing",
        severity="high",
        recommendation="核查资质",
        confirmed=False,
    )
    defaults.update(kwargs)
    return DisqualificationClause(**defaults)


@pytest.fixture
def override_db() -> Generator:
    def _override(results: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = results
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/documents/{DOC_ID}/disqualification-clauses"


class TestGetDisqualificationClauses:
    @pytest.mark.asyncio
    async def test_get_returns_items(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(_tender_doc()), _scalars_result([_clause()])])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["title"] == "资质要求"
        assert items[0]["severity"] == "high"
        assert items[0]["confirmed"] is False

    @pytest.mark.asyncio
    async def test_get_forbidden_for_non_member(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.get(_url(), headers=_headers(OTHER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_doc_not_found(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 404


class TestPutDisqualificationClauses:
    @pytest.mark.asyncio
    async def test_put_overwrites_with_audit_and_commit(
        self, client: AsyncClient, override_db
    ) -> None:
        session = override_db([_result(_project()), _result(_tender_doc()), _scalars_result([])])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action))

        body = {
            "items": [
                {
                    "clause_no": "2.1",
                    "title": "资质要求",
                    "risk_category": "qualification_missing",
                    "severity": "high",
                    "recommendation": "核查资质",
                    "confirmed": True,
                }
            ]
        }
        with patch.object(documents_api.audit, "record", fake_record):
            resp = await client.put(_url(), headers=_headers(OWNER_ID), json=body)
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["confirmed"] is True
        assert recorded == [(OWNER_ID, "document.disqualification_clauses_update")]
        assert session.commit.await_count == 1
        # 删旧（execute delete）+ 插新（session.add）
        assert session.add.await_count == 1 or session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_put_cleans_invalid_items(self, client: AsyncClient, override_db) -> None:
        """缺 title 丢弃；非法 severity/risk_category 归一."""
        override_db([_result(_project()), _result(_tender_doc()), _scalars_result([])])
        body = {
            "items": [
                {"clause_no": "1", "title": "", "severity": "high"},
                {
                    "clause_no": "2",
                    "title": "暗标规则",
                    "risk_category": "unknown_cat",
                    "severity": "weird",
                },
            ]
        }
        resp = await client.put(_url(), headers=_headers(OWNER_ID), json=body)
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["risk_category"] == "other"
        assert items[0]["severity"] == "mid"

    @pytest.mark.asyncio
    async def test_put_rejects_non_tender_doc(self, client: AsyncClient, override_db) -> None:
        doc = _tender_doc()
        doc.doc_type = "kb_material"
        override_db([_result(_project()), _result(doc)])
        resp = await client.put(_url(), headers=_headers(OWNER_ID), json={"items": []})
        assert resp.status_code == 400
        assert resp.json()["code"] == 4010


class TestProjectLevelEndpoints:
    @pytest.mark.asyncio
    async def test_project_clauses_aggregate(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _scalars_result([_clause(), _clause(clause_no="3.2")])])
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/disqualification-clauses", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_disqualification_risks_returns_mapping(
        self, client: AsyncClient, override_db
    ) -> None:
        override_db([_result(_project()), _scalars_result([_clause(confirmed=True)])])
        risks = {"ch03": [{"clause_no": "2.1", "title": "资质要求", "severity": "high"}]}
        with patch.object(
            documents_api.dq_service, "scan_project_sections", AsyncMock(return_value=risks)
        ):
            resp = await client.get(
                f"/api/v1/projects/{PROJECT_ID}/disqualification-risks", headers=_headers(OWNER_ID)
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["risks"] == risks


class TestExportGate:
    @pytest.mark.asyncio
    async def test_export_blocked_by_unconfirmed_high(
        self, client: AsyncClient, override_db
    ) -> None:
        """存在未确认 high 废标条款 → 4012 阻塞导出."""
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        override_db([_result(_project()), count_result])
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/workflow/export", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4012

    @pytest.mark.asyncio
    async def test_export_passes_when_all_confirmed(self, client: AsyncClient, override_db) -> None:
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        override_db([_result(_project()), count_result])
        with patch.object(
            workflow_api.workflow_runtime,
            "export_workflow",
            AsyncMock(return_value={"download_url": "http://x"}),
        ):
            resp = await client.get(
                f"/api/v1/projects/{PROJECT_ID}/workflow/export", headers=_headers(OWNER_ID)
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["download_url"] == "http://x"
