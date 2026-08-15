"""文档 API 测试."""

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_document_no_auth(client: AsyncClient) -> None:
    """未认证上传文档返回 401."""
    import io

    files = {"file": ("test.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/documents",
        files=files,
        params={"doc_type": "tender_file"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_documents_no_auth(client: AsyncClient) -> None:
    """未认证列出文档返回 401."""
    response = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000001/documents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_score_points_no_auth(client: AsyncClient) -> None:
    """未认证列出评分点返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/score-points"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tech_requirements_no_auth(client: AsyncClient) -> None:
    """未认证列出技术需求返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/tech-requirements"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_score_point_no_auth(client: AsyncClient) -> None:
    """未认证更新评分点返回 401."""
    response = await client.put(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/score-points/00000000-0000-0000-0000-000000000001",
        json={"strategy": "test"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_invalid_file_type(client: AsyncClient) -> None:
    """上传不支持的文件类型 — 需要认证所以先返回 401."""
    import io

    files = {"file": ("test.exe", io.BytesIO(b"fake"), "application/x-msdownload")}
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/documents",
        files=files,
        params={"doc_type": "tender_file"},
    )
    # 没有 token 所以先返回 401
    assert response.status_code == 401


# ── 上传成功后异步入队（task_service）──


class _FakeUploadSession:
    """mock 会话：成员校验返回 owner；flush 时补齐主键、refresh 时补齐 created_at."""

    def __init__(self, project) -> None:
        self._project = project
        self.added: list = []

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._project
        return result

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, obj) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)


@pytest.fixture
def upload_env(monkeypatch):
    """上传端点环境：mock 会话/对象存储/任务入队，真实 JWT 鉴权."""
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models.project import Project

    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=user_id)
    session = _FakeUploadSession(project)
    app.dependency_overrides[get_db] = lambda: session

    monkeypatch.setattr("app.api.documents.upload_file", lambda *a, **k: "mock/storage/key")

    calls: dict[str, list] = {"parse": [], "index": []}

    async def fake_enqueue_parse(pid, did):
        calls["parse"].append((pid, did))
        return True

    async def fake_enqueue_index(pid, did):
        calls["index"].append((pid, did))
        return True

    monkeypatch.setattr("app.services.task_service.enqueue_parse_tender", fake_enqueue_parse)
    monkeypatch.setattr("app.services.task_service.enqueue_index_document", fake_enqueue_index)

    yield {
        "user_id": user_id,
        "project_id": project_id,
        "session": session,
        "calls": calls,
        "headers": {"Authorization": f"Bearer {create_access_token(str(user_id))}"},
    }
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_tender_file_enqueues_parse(client: AsyncClient, upload_env) -> None:
    """招标文件上传成功 → 入队 task_parse_tender（不入队向量化）."""
    files = {"file": ("tender.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        f"/api/v1/projects/{upload_env['project_id']}/documents",
        files=files,
        params={"doc_type": "tender_file"},
        headers=upload_env["headers"],
    )
    assert response.status_code == 200
    doc_id = uuid.UUID(response.json()["data"]["id"])
    assert upload_env["calls"]["parse"] == [(upload_env["project_id"], doc_id)]
    assert upload_env["calls"]["index"] == []
    # 上传端点只入队，状态推进由 worker 负责，仍为 uploaded
    assert response.json()["data"]["status"] == "uploaded"


@pytest.mark.asyncio
async def test_upload_kb_material_enqueues_index(client: AsyncClient, upload_env) -> None:
    """资料库文档上传成功 → 入队 task_index_document（不入队解析）."""
    files = {"file": ("kb.pdf", io.BytesIO(b"fake pdf"), "application/pdf")}
    response = await client.post(
        f"/api/v1/projects/{upload_env['project_id']}/documents",
        files=files,
        params={"doc_type": "kb_material"},
        headers=upload_env["headers"],
    )
    assert response.status_code == 200
    doc_id = uuid.UUID(response.json()["data"]["id"])
    assert upload_env["calls"]["index"] == [(upload_env["project_id"], doc_id)]
    assert upload_env["calls"]["parse"] == []
