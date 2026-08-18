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
async def test_confirm_outline_passes_mounted_kb_ids_to_resume(client, monkeypatch) -> None:
    """mounted_kb_ids 经 resume payload 传递（知识库级挂载，与文档级并存）."""
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

    kb_id, doc_id = uuid.uuid4(), uuid.uuid4()
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/confirm-outline",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"mounted_kb_ids": [str(kb_id)], "mounted_doc_ids": [str(doc_id)]},
        )
        assert response.status_code == 200
        _pid, resume_value = captured["resume"]
        assert resume_value["mounted_kb_ids"] == [str(kb_id)]
        assert resume_value["mounted_doc_ids"] == [str(doc_id)]
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
    unassigned = MagicMock()  # 章节级权限查询：未分配 → 可编辑
    unassigned.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result, unassigned])
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
    unassigned = MagicMock()
    unassigned.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result, unassigned])
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
async def test_save_section_edit_non_assignee_forbidden(client: AsyncClient) -> None:
    """已分配章节：非 assignee 且非 owner 编辑 → 403（可视不可改）."""
    from app.models.project import ProjectMember
    from app.models.proposal import ChapterAssignment

    owner_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    member_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    assignment = ChapterAssignment(
        project_id=project_id,
        chapter_no="1",
        title="项目概述",
        assignee_id=assignee_id,
        assigned_by=owner_id,
    )

    def _result(obj):
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        return r

    session = AsyncMock()
    session.execute.side_effect = [
        _result(project),  # _check_project_member 查 project（非 owner）
        _result(ProjectMember(project_id=project_id, user_id=member_id)),  # 成员表命中
        _result(assignment),  # 章节已分配给他人
        _result(project),  # owner 兜底判定（非 owner）
    ]
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = await client.put(
            f"/api/v1/projects/{project_id}/workflow/sections/1",
            headers={"Authorization": f"Bearer {create_access_token(str(member_id))}"},
            json={"content": "x"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_outline_suggest_no_auth(client: AsyncClient) -> None:
    """未认证生成大纲建议返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/outline-suggest"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_outline_suggest_requires_pending_interrupt(client: AsyncClient, monkeypatch) -> None:
    """非 confirm_outline 挂起态生成建议 → 4009."""
    from app.core.exceptions import BizError
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    app.dependency_overrides[get_db] = lambda: session

    async def fake_ensure(pid, expected_type) -> None:
        raise BizError(code=4009, message="当前没有待处理的工作流中断，操作无效")

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/outline-suggest",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 4009
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_outline_suggest_returns_suggestions(client: AsyncClient, monkeypatch) -> None:
    """生成建议：读 state 的 score_points/outline → build 建议 → 返回."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_ensure(pid, expected_type) -> None:
        captured["ensure"] = expected_type

    async def fake_status(pid) -> dict:
        return {"score_points": [{"clause_no": "4.2"}], "outline": [{"chapter_no": "2"}]}

    async def fake_build(score_points, outline) -> list:
        captured["build"] = (score_points, outline)
        return [{"suggestion_id": "add_section:2:4.2:x", "suggestion_type": "add_section"}]

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    monkeypatch.setattr(workflow_runtime, "get_status_dict", fake_status)
    monkeypatch.setattr(
        "app.services.outline_suggest_service.build_outline_suggestions", fake_build
    )
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/outline-suggest",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["suggestions"][0]["suggestion_type"] == "add_section"
        assert captured["ensure"] == "confirm_outline"
        assert captured["build"][0] == [{"clause_no": "4.2"}]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_outline_suggest_apply_returns_adjusted_outline(
    client: AsyncClient, monkeypatch
) -> None:
    """采纳建议：adopted 传递 → apply 返回调整后大纲（不写 state）."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_ensure(pid, expected_type) -> None:
        captured["ensure"] = expected_type

    async def fake_status(pid) -> dict:
        return {"outline": [{"chapter_no": "2", "title": "技术方案"}]}

    def fake_apply(outline, adopted) -> list:
        captured["apply"] = (outline, adopted)
        return [{"chapter_no": "2", "title": "技术方案", "sections": ["进度计划"]}]

    monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
    monkeypatch.setattr(workflow_runtime, "get_status_dict", fake_status)
    monkeypatch.setattr(
        "app.services.outline_suggest_service.apply_outline_suggestions", fake_apply
    )
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/outline-suggest/apply",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"adopted": ["add_section:2:4.2:progress"]},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["outline"][0]["sections"] == ["进度计划"]
        assert captured["ensure"] == "confirm_outline"
        assert captured["apply"][1] == ["add_section:2:4.2:progress"]
        assert captured["apply"][0][0]["title"] == "技术方案", "应读 state 大纲应用"
        actions = [c.args[0].action for c in session.add.call_args_list]
        assert "workflow.outline_suggest_apply" in actions
        session.commit.assert_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_section_suggest_no_auth(client: AsyncClient) -> None:
    """未认证生成内容建议返回 401."""
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/workflow/section-suggest"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_section_suggest_returns_suggestions(client: AsyncClient, monkeypatch) -> None:
    """内容建议：读 state chapters/score_points → build → 返回（含指定章节）."""
    from app.services import workflow_runtime

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="测试项目", owner_id=owner_id)
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    app.dependency_overrides[get_db] = lambda: session

    captured: dict = {}

    async def fake_status(pid) -> dict:
        return {"chapters": {"1": "内容"}, "score_points": [{"clause_no": "1"}]}

    async def fake_build(chapters, score_points, chapter_no=None) -> list:
        captured["build"] = (chapters, score_points, chapter_no)
        return [{"chapter_no": "1", "issue": "缺少验收标准", "severity": "high"}]

    monkeypatch.setattr(workflow_runtime, "get_status_dict", fake_status)
    monkeypatch.setattr(
        "app.services.section_suggest_service.build_section_suggestions", fake_build
    )
    try:
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflow/section-suggest",
            headers={"Authorization": f"Bearer {create_access_token(str(owner_id))}"},
            json={"chapter_no": "1"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["suggestions"][0]["issue"] == "缺少验收标准"
        assert captured["build"][0] == {"1": "内容"}
        assert captured["build"][2] == "1", "body.chapter_no 应传递"
        actions = [c.args[0].action for c in session.add.call_args_list]
        assert "workflow.section_suggest" in actions
        session.commit.assert_awaited()
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


class TestRedispatchFeedback:
    """confirm-review 意见回派（阶段 5）：命中分工 → 打回负责人；无分工 → 保留 rewrite."""

    def _env(self, monkeypatch, assignment, outline):
        import app.api.workflow as workflow_api
        from app.services import workflow_runtime

        owner_id = uuid.uuid4()
        project_id = uuid.uuid4()
        project = Project(id=project_id, name="测试项目", owner_id=owner_id)
        session = AsyncMock()
        session.add = MagicMock()
        session.execute.side_effect = [_result(project), _result(assignment)]
        app.dependency_overrides[get_db] = lambda: session

        captured: dict = {"published": []}

        async def fake_ensure(pid, expected_type) -> None:
            pass

        def fake_resume(pid, resume_value) -> None:
            captured["resume"] = resume_value

        async def fake_get_state(pid):
            snapshot = MagicMock()
            snapshot.values = {"outline": outline}
            return snapshot

        async def fake_publish(pid, event):
            captured["published"].append(event)

        monkeypatch.setattr(workflow_runtime, "ensure_pending_interrupt", fake_ensure)
        monkeypatch.setattr(workflow_runtime, "resume_workflow_in_background", fake_resume)
        monkeypatch.setattr(workflow_runtime, "get_state", fake_get_state)
        monkeypatch.setattr(workflow_api, "publish_event", fake_publish)
        return {
            "owner_id": owner_id,
            "project_id": project_id,
            "session": session,
            "captured": captured,
        }

    @pytest.mark.asyncio
    async def test_hit_assignment_rejected_and_removed(self, client, monkeypatch) -> None:
        """chapter_no 命中分工：打回 + 推 task_reviewed + 不再进 rewrite feedback."""
        from app.models.proposal import ChapterAssignment

        assignment = ChapterAssignment(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            chapter_no="1",
            title="项目概述",
            assignee_id=uuid.uuid4(),
            assigned_by=uuid.uuid4(),
            status="approved",
        )
        env = self._env(
            monkeypatch, assignment, [{"chapter_no": "1", "title": "项目概述"}]
        )
        try:
            resp = await client.post(
                f"/api/v1/projects/{env['project_id']}/workflow/confirm-review",
                headers={"Authorization": f"Bearer {create_access_token(str(env['owner_id']))}"},
                json={"action": "feedback", "feedback": {"1": "缺少进度计划"}},
            )
            assert resp.status_code == 200
            assert assignment.status == "rejected"
            assert assignment.review_comment == "缺少进度计划"
            # 全部回派 → resume action 改 redispatched（图路由回 review 重新挂起）
            assert env["captured"]["resume"]["action"] == "redispatched"
            assert env["captured"]["resume"]["feedback"] == {}
            assert resp.json()["data"]["next_phase"] == "redispatch"
            assert env["captured"]["published"][0]["type"] == "task_reviewed"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_title_key_matches_chapter(self, client, monkeypatch) -> None:
        """标题键匹配章节 → 同样回派."""
        from app.models.proposal import ChapterAssignment

        assignment = ChapterAssignment(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            chapter_no="2",
            title="技术方案",
            assignee_id=uuid.uuid4(),
            assigned_by=uuid.uuid4(),
            status="approved",
        )
        env = self._env(
            monkeypatch, assignment, [{"chapter_no": "2", "title": "技术方案"}]
        )
        try:
            resp = await client.post(
                f"/api/v1/projects/{env['project_id']}/workflow/confirm-review",
                headers={"Authorization": f"Bearer {create_access_token(str(env['owner_id']))}"},
                json={"action": "feedback", "feedback": {"技术方案": "补充架构图"}},
            )
            assert resp.status_code == 200
            assert assignment.status == "rejected"
            assert env["captured"]["resume"]["feedback"] == {}
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_no_assignment_keeps_rewrite(self, client, monkeypatch) -> None:
        """无分工章节：意见保留在 feedback（原 rewrite 链路）."""
        env = self._env(monkeypatch, None, [{"chapter_no": "3", "title": "实施计划"}])
        try:
            resp = await client.post(
                f"/api/v1/projects/{env['project_id']}/workflow/confirm-review",
                headers={"Authorization": f"Bearer {create_access_token(str(env['owner_id']))}"},
                json={"action": "feedback", "feedback": {"3": "细化里程碑"}},
            )
            assert resp.status_code == 200
            assert env["captured"]["resume"]["feedback"] == {"3": "细化里程碑"}
            assert env["captured"]["published"] == []
        finally:
            app.dependency_overrides.pop(get_db, None)


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result
