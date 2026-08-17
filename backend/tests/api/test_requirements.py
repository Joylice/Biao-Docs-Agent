"""技术需求梳理 API 测试（POST generate / GET requirements）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.fixture
def req_env(monkeypatch):
    """requirements 路由环境：mock 会话（成员校验）/服务层，真实 JWT 鉴权."""
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)

    session = AsyncMock()
    session.execute.side_effect = [_result(project)]
    app.dependency_overrides[get_db] = lambda: session

    generate_mock = AsyncMock(
        return_value={
            "total": 2,
            "mapped": 1,
            "items": [
                {
                    "id": str(uuid.uuid4()),
                    "seq": 6,
                    "description": "支持≥100并发",
                    "category": "性能",
                    "is_mandatory": True,
                    "sp_id": str(uuid.uuid4()),
                    "source": "sp_derived",
                    "related_sp": {"clause_no": "2.2.2(1)", "item": "技术方案"},
                },
                {
                    "id": str(uuid.uuid4()),
                    "seq": 7,
                    "description": "通用需求",
                    "category": None,
                    "is_mandatory": False,
                    "sp_id": None,
                    "source": "tender",
                    "related_sp": None,
                },
            ],
        }
    )
    list_mock = AsyncMock(return_value=generate_mock.return_value["items"])
    monkeypatch.setattr("app.services.requirements_service.generate_requirements", generate_mock)
    monkeypatch.setattr("app.services.requirements_service.list_requirements", list_mock)
    monkeypatch.setattr("app.core.audit.record", AsyncMock())

    yield {
        "owner_id": owner_id,
        "project_id": project_id,
        "generate": generate_mock,
        "list": list_mock,
        "headers": {"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
    }
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_generate_requirements_no_auth(client: AsyncClient) -> None:
    """未认证梳理技术需求返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/requirements/generate",
        json={},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_requirements_no_auth(client: AsyncClient) -> None:
    """未认证列出技术需求（映射视图）返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/requirements"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_generate_defaults_to_confirmed_points(client: AsyncClient, req_env) -> None:
    """省略 score_point_ids → 服务层收到 None（取全部已确认评分点）."""
    response = await client.post(
        f"/api/v1/projects/{req_env['project_id']}/requirements/generate",
        json={},
        headers=req_env["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 2
    assert body["data"]["mapped"] == 1
    req_env["generate"].assert_awaited_once()
    _, kwargs = req_env["generate"].call_args
    pid = req_env["generate"].call_args.args[1]
    assert pid == req_env["project_id"]
    assert kwargs.get("score_point_ids") is None


@pytest.mark.asyncio
async def test_generate_with_explicit_ids(client: AsyncClient, req_env) -> None:
    """显式传 score_point_ids → 透传服务层（勾选再梳理）."""
    sp_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/projects/{req_env['project_id']}/requirements/generate",
        json={"score_point_ids": [sp_id]},
        headers=req_env["headers"],
    )
    assert response.status_code == 200, response.text
    kwargs = req_env["generate"].call_args.kwargs
    assert [str(i) for i in kwargs.get("score_point_ids", [])] == [sp_id]


@pytest.mark.asyncio
async def test_list_requirements_only_mapped_param(client: AsyncClient, req_env) -> None:
    """only_mapped 查询参数透传服务层."""
    response = await client.get(
        f"/api/v1/projects/{req_env['project_id']}/requirements",
        params={"only_mapped": "true"},
        headers=req_env["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert len(body["data"]) == 2
    assert body["data"][0]["related_sp"]["clause_no"] == "2.2.2(1)"
    assert body["data"][1]["related_sp"] is None
    kwargs = req_env["list"].call_args.kwargs
    assert kwargs.get("only_mapped") is True
