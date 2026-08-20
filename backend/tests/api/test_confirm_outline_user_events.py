"""confirm-outline 用户级事件测试 — 阶段 C：大纲确认后推送 workbench_refresh.

契约：owner 确认大纲后，向项目全体成员（含 owner，去重）的用户频道
推送 {"type":"workbench_refresh","project_id":...}，驱动工作台刷新。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

import app.api.workflow as workflow_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _scalars_result(values: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_confirm_outline_pushes_workbench_refresh_to_members(
    client: AsyncClient, monkeypatch
) -> None:
    """确认大纲后向成员+owner 频道推送 workbench_refresh（去重）."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    member_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)

    session = AsyncMock()
    session.execute.side_effect = [
        _result(project),  # get_current_owner_id
        _scalars_result([owner_id, member_id]),  # 成员列表（owner 在成员表）
    ]
    app.dependency_overrides[get_db] = lambda: session

    user_events: list = []

    async def fake_ensure(pid, expected_type) -> None:
        pass

    def fake_resume(pid, resume_value) -> None:
        pass

    async def fake_publish_user(uid, event):
        user_events.append((uid, event))

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    monkeypatch.setattr(workflow_runtime, "resume_workflow_in_background", fake_resume)
    monkeypatch.setattr(workflow_api, "publish_user_event", fake_publish_user)
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/confirm-outline",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        targets = {uid for uid, _ in user_events}
        assert targets == {str(owner_id), str(member_id)}
        assert all(ev["type"] == "workbench_refresh" for _, ev in user_events)
        assert all(ev["project_id"] == str(project_id) for _, ev in user_events)
    finally:
        app.dependency_overrides.pop(get_db, None)
