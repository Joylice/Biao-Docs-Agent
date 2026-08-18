"""格式要求 API 测试 — GET/PUT /projects/{project_id}/documents/{doc_id}/format-requirements.

覆盖：
- GET：成员读取格式要求列表、非成员 403、文档不存在 404
- PUT：幂等覆盖 + 审计 + 显式 commit、非招标文件 4010、条目清洗（缺 requirement 丢弃）
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.api.documents as documents_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import Document
from app.models.project import Project

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _tender_doc(meta: dict | None = None) -> Document:
    doc = Document(
        id=DOC_ID,
        project_id=PROJECT_ID,
        doc_type="tender_file",
        title="招标文件.docx",
        storage_key="k",
        status="parsed",
    )
    doc.meta = meta if meta is not None else {}
    return doc


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


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/documents/{DOC_ID}/format-requirements"


class TestGetFormatRequirements:
    @pytest.mark.asyncio
    async def test_get_returns_items(self, client: AsyncClient, override_db) -> None:
        """成员读取：返回 meta.format_requirements；无数据时空列表."""
        fr = [{"category": "font_body", "requirement": "正文宋体小四"}]
        override_db([_project(), _tender_doc({"format_requirements": fr})])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == fr

    @pytest.mark.asyncio
    async def test_get_empty_when_meta_missing(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), _tender_doc({})])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_get_forbidden_for_non_member(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.get(_url(), headers=_headers(OTHER_ID))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_doc_not_found(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 404


class TestPutFormatRequirements:
    @pytest.mark.asyncio
    async def test_put_overwrites_with_audit_and_commit(
        self, client: AsyncClient, override_db
    ) -> None:
        """幂等覆盖 meta.format_requirements + 审计 + 显式 commit."""
        doc = _tender_doc({"format_requirements": [{"category": "other", "requirement": "旧"}]})
        session = override_db([_project(), doc])
        recorded: list = []

        async def fake_record(db, user_id, action, **kwargs):
            recorded.append((user_id, action))

        new_items = [
            {"category": "font_body", "requirement": "正文宋体小四"},
            {"category": "margin", "requirement": "上下2.54cm 左右3.17cm"},
        ]
        with patch.object(documents_api.audit, "record", fake_record):
            resp = await client.put(
                _url(), headers=_headers(OWNER_ID), json={"format_requirements": new_items}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == new_items
        assert doc.meta["format_requirements"] == new_items
        assert recorded == [(OWNER_ID, "document.format_requirements_update")]
        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_put_drops_items_without_requirement(
        self, client: AsyncClient, override_db
    ) -> None:
        """缺 requirement 的条目被清洗丢弃."""
        doc = _tender_doc()
        override_db([_project(), doc])
        resp = await client.put(
            _url(),
            headers=_headers(OWNER_ID),
            json={
                "format_requirements": [
                    {"category": "font_body", "requirement": "正文宋体小四"},
                    {"category": "binding"},
                    {"requirement": ""},
                ]
            },
        )
        assert resp.status_code == 200
        assert doc.meta["format_requirements"] == [
            {"category": "font_body", "requirement": "正文宋体小四"}
        ]

    @pytest.mark.asyncio
    async def test_put_rejects_non_tender_doc(self, client: AsyncClient, override_db) -> None:
        """仅招标文件可维护格式要求 → 4010."""
        doc = _tender_doc()
        doc.doc_type = "kb_material"
        override_db([_project(), doc])
        resp = await client.put(
            _url(), headers=_headers(OWNER_ID), json={"format_requirements": []}
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4010

    @pytest.mark.asyncio
    async def test_put_forbidden_for_non_member(self, client: AsyncClient, override_db) -> None:
        override_db([_project(), None])
        resp = await client.put(
            _url(), headers=_headers(OTHER_ID), json={"format_requirements": []}
        )
        assert resp.status_code == 403
