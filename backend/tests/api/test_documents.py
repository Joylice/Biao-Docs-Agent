"""文档 API 测试."""

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
