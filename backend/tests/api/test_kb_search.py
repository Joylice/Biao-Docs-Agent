"""KB 资料检索 API 测试 — GET /projects/{pid}/kb/search（E2E-03 检索命中缺口补齐）."""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project

OWNER_ID = uuid.uuid4()
OUTSIDER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _owned_project() -> Project:
    return Project(id=PROJECT_ID, owner_id=OWNER_ID, name="检索测试项目")


@pytest.fixture
def override_db() -> Generator:
    """按预设结果序列覆盖 get_db，用例结束清理."""

    def _override(scalar_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = [_result(s) for s in scalar_sequence]
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_kb_search_no_auth(client: AsyncClient) -> None:
    """未认证检索返回 401."""
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/kb/search", params={"q": "高可用"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_kb_search_by_non_member_returns_403(client: AsyncClient, override_db) -> None:
    """已认证非成员检索 → 403 / code 4003."""
    override_db([_owned_project(), None])
    token = create_access_token(str(OUTSIDER_ID))
    resp = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/kb/search",
        params={"q": "高可用"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_kb_search_returns_hits(client: AsyncClient, override_db, monkeypatch) -> None:
    """成员检索 → 200，返回 items（含文档标题/相似度），委托 rag_service."""
    override_db([_owned_project()])
    token = create_access_token(str(OWNER_ID))

    captured: dict = {}

    async def fake_search_materials(db, project_id, query, top_k=5, min_score=0.0):
        captured["project_id"] = project_id
        captured["query"] = query
        captured["top_k"] = top_k
        return [
            {
                "chunk_id": str(uuid.uuid4()),
                "doc_id": str(uuid.uuid4()),
                "title": "product-handbook.pdf",
                "content": "支持高可用部署",
                "page_no": 1,
                "score": 0.9,
            }
        ]

    monkeypatch.setattr("app.services.rag_service.search_materials", fake_search_materials)

    resp = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/kb/search",
        params={"q": "高可用", "top_k": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "product-handbook.pdf"
    assert captured["project_id"] == PROJECT_ID
    assert captured["query"] == "高可用"
    assert captured["top_k"] == 3
