"""项目级接口越权用例 — 已认证非成员访问 → 403（security.md §3）.

说明（如实标注，非伪造通过）：
- 测试环境无可用 PostgreSQL（localhost:5432 连接超时），conftest 亦无真实 DB fixture；
- 模型使用 postgresql.UUID 列类型，sqlite 内存库不可行；
- 因此数据层结果经 ``app.dependency_overrides[get_db]`` + mock 会话注入
  （与 tests/unit/test_audit.py 的 MagicMock 风格一致），用例真实走通
  JWT 解码 → 路由处理 → ``_check_project_member`` 鉴权 → BizError 统一处理
  （code=4003 → HTTP 403）的完整链路。
"""

import io
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


def _mock_session(scalar_sequence: list) -> AsyncMock:
    """mock 会话：按顺序为每次 execute 返回预设标量结果."""
    session = AsyncMock()
    session.execute.side_effect = [_result(s) for s in scalar_sequence]
    return session


def _owned_project() -> Project:
    """存在的项目，owner 为用户 A."""
    return Project(id=PROJECT_ID, owner_id=OWNER_ID, name="测试项目")


@pytest.fixture
def outsider_headers() -> dict[str, str]:
    """用户 B（已认证、非项目成员）的请求头."""
    token = create_access_token(str(OUTSIDER_ID))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def override_db() -> Generator:
    """按预设结果序列覆盖 get_db，用例结束清理."""

    def _override(scalar_sequence: list) -> AsyncMock:
        session = _mock_session(scalar_sequence)
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


# ── projects ──


@pytest.mark.asyncio
async def test_get_project_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """项目详情：非成员 → 403 / code 4003."""
    # get_project 查项目一次 + _check_project_member 查项目一次、查成员一次（非成员）
    override_db([_owned_project(), _owned_project(), None])
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}", headers=outsider_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_add_member_by_non_owner_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """添加成员：非 owner → 403 / code 4003."""
    override_db([_owned_project()])
    resp = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/members",
        headers=outsider_headers,
        json={"email": "someone@example.com"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


# ── documents ──


@pytest.mark.asyncio
async def test_list_documents_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """文档列表：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/documents", headers=outsider_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_upload_document_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """文档上传：非成员 → 403 / code 4003（成员校验先于文件校验）."""
    override_db([_owned_project(), None])
    files = {"file": ("test.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    resp = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/documents",
        headers=outsider_headers,
        files=files,
        params={"doc_type": "tender_file"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_list_score_points_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """评分点列表：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/score-points", headers=outsider_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


# ── workflow ──


@pytest.mark.asyncio
async def test_start_workflow_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """启动工作流：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=outsider_headers
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_workflow_status_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """工作流状态：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/workflow/status", headers=outsider_headers
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_confirm_score_points_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """确认评分点：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-score-points",
        headers=outsider_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_confirm_review_by_non_member_returns_403(
    client: AsyncClient, override_db, outsider_headers: dict[str, str]
) -> None:
    """确认审阅：非成员 → 403 / code 4003."""
    override_db([_owned_project(), None])
    resp = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
        headers=outsider_headers,
        json={"action": "approved"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 4003
