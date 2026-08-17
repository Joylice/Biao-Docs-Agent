"""工作流 API 测试."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project


@pytest.mark.asyncio
async def test_start_workflow_no_auth(client: AsyncClient) -> None:
    """未认证启动工作流返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/start"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_workflow_status_no_auth(client: AsyncClient) -> None:
    """未认证获取工作流状态返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/status"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_score_points_no_auth(client: AsyncClient) -> None:
    """未认证确认评分点返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-score-points"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_outline_no_auth(client: AsyncClient) -> None:
    """未认证确认大纲返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-outline"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_review_no_auth(client: AsyncClient) -> None:
    """未认证确认审阅返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/confirm-review"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_no_auth(client: AsyncClient) -> None:
    """未认证导出返回 401."""
    response = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/export"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_regenerate_outline_no_auth(client: AsyncClient) -> None:
    """未认证重新生成大纲返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/regenerate-outline"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_confirm_outline_passes_edited_outline_to_resume(client, monkeypatch) -> None:
    """确认大纲携带编辑后 outline → resume payload 原样传递（不再 update_state 清 interrupt）."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_ensure(pid, expected_type) -> None:
        captured["ensure"] = (pid, expected_type)

    def fake_resume(pid, resume_value) -> None:
        captured["resume"] = (pid, resume_value)

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    monkeypatch.setattr(workflow_runtime, "resume_workflow_in_background", fake_resume)

    edited = [{"chapter_no": "1", "title": "编辑后标题", "covered_clauses": ["1"]}]
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/confirm-outline",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"outline": edited},
        )
        assert response.status_code == 200
        assert captured["ensure"][1] == "confirm_outline"
        _pid, resume_value = captured["resume"]
        assert resume_value["confirmed"] is True
        assert resume_value["outline"] == edited
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_confirm_outline_passes_mounted_doc_ids_to_resume(client, monkeypatch) -> None:
    """mounted_doc_ids 经 resume payload 传递（字符串化 UUID 列表）."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_ensure(pid, expected_type) -> None:
        captured["ensure"] = (pid, expected_type)

    def fake_resume(pid, resume_value) -> None:
        captured["resume"] = (pid, resume_value)

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    monkeypatch.setattr(workflow_runtime, "resume_workflow_in_background", fake_resume)

    doc_id = uuid.uuid4()
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/confirm-outline",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"mounted_doc_ids": [str(doc_id)]},
        )
        assert response.status_code == 200
        _pid, resume_value = captured["resume"]
        assert resume_value["mounted_doc_ids"] == [str(doc_id)]
        assert "outline" not in resume_value, "未提交 outline 时不得注入空大纲"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_save_section_edit_no_auth(client: AsyncClient) -> None:
    """未认证保存章节返回 401."""
    response = await client.put(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/sections/1",
        json={"content": "x"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_save_section_edit_success(client: AsyncClient, monkeypatch) -> None:
    """PUT sections/{chapter_no}：成员校验 + 调服务 + 审计 + 显式 commit."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()  # audit.record 同步调用 add
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_save(db, pid, chapter_no, content) -> None:
        captured["save"] = (str(pid), chapter_no, content)

    monkeypatch.setattr(workflow_runtime, "save_section_edit", fake_save)
    try:
        response = await client.put(
            f"/api/v1/projects/{project_id}/workflow/sections/1",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"content": "人工编辑内容"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["saved"] is True
        assert captured["save"][1] == "1"
        assert captured["save"][2] == "人工编辑内容"
        session.commit.assert_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_save_section_edit_chapter_not_found(client: AsyncClient, monkeypatch) -> None:
    """章节不存在 → 4004."""
    from app.core.exceptions import BizError
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: session

    async def fake_save(db, pid, chapter_no, content) -> None:
        raise BizError(code=4004, message=f"章节 {chapter_no} 尚未生成，无法保存")

    monkeypatch.setattr(workflow_runtime, "save_section_edit", fake_save)
    try:
        response = await client.put(
            f"/api/v1/projects/{project_id}/workflow/sections/99",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"content": "x"},
        )
        assert response.status_code == 404
        assert response.json()["code"] == 4004
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_save_section_edit_non_member_forbidden(client: AsyncClient) -> None:
    """非成员保存章节 → 403（真实执行成员校验）."""
    from app.models.project import ProjectMember

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    session = AsyncMock()

    def _execute(stmt, *a, **k):
        entity = stmt.column_descriptions[0]["entity"]
        result = MagicMock()
        if entity is Project:
            result.scalar_one_or_none.return_value = project
        elif entity is ProjectMember:
            result.scalar_one_or_none.return_value = None  # 成员表查无此人
        else:
            raise AssertionError(f"未预期查询实体: {entity}")
        return result

    session.execute.side_effect = _execute
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.put(
            f"/api/v1/projects/{project_id}/workflow/sections/1",
            headers={"Authorization": f"Bearer {create_access_token(str(uuid.uuid4()))}"},
            json={"content": "x"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_start_workflow_commits_audit(client: AsyncClient, monkeypatch) -> None:
    """BUG-1：启动工作流的审计写入在响应前显式 commit."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()  # audit.record 同步调用 add
    app.dependency_overrides[get_db] = lambda: session

    async def fake_status(_pid) -> dict:
        return {"phase": "init", "progress": 0.0}

    monkeypatch.setattr(workflow_runtime, "start_workflow_in_background", lambda pid, uid: None)
    monkeypatch.setattr(workflow_runtime, "get_status_dict", fake_status)

    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/start",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        session.commit.assert_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)
