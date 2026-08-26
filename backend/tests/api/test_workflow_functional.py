"""工作流 API 功能测试 — InMemorySaver + LLM mock 驱动真实图（API → runtime → graph）.

parse 节点的数据经 monkeypatch nodes.async_session_factory 注入 FakeDB
（与 tests/agents/test_graph.py 同风格）；API 层的成员校验/审计经
dependency_overrides[get_db] 注入 mock 会话（与 test_authorization.py 同风格）。
"""

import asyncio
import uuid
from collections.abc import Callable
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import nodes
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import ScorePoint, TechRequirement
from app.models.project import Project, ProjectMember
from app.models.proposal import ProposalSkeleton
from app.services.infra import workflow_runtime
from tests.agents.test_graph import FakeDB

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
FAKE_EXPORT_KEY = f"{PROJECT_ID}/export/api-test.docx"


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _owned_project() -> Project:
    return Project(id=PROJECT_ID, owner_id=OWNER_ID, name="API 功能测试项目", tender_no="TN-API-1")


def _node_db() -> FakeDB:
    """parse/retrieve/write 等节点内部 session 的 mock 数据（is_star=False 避免校验重试）."""
    return FakeDB(
        {
            Project: [_owned_project()],
            ScorePoint: [
                ScorePoint(
                    id=uuid.uuid4(),
                    project_id=PROJECT_ID,
                    doc_id=uuid.uuid4(),
                    clause_no="1",
                    item="技术方案完整性",
                    score=10,
                    criteria="方案完整",
                    is_star=False,
                    confirmed=True,  # 严格模式：仅已确认评分点进入大纲
                )
            ],
            TechRequirement: [
                TechRequirement(
                    id=uuid.uuid4(),
                    project_id=PROJECT_ID,
                    doc_id=uuid.uuid4(),
                    seq=1,
                    description="支持高可用",
                    category="架构",
                    is_mandatory=True,
                )
            ],
        }
    )


@pytest.fixture
def runtime_memory():
    """workflow_runtime 注入 InMemorySaver."""
    workflow_runtime.set_saver(InMemorySaver())
    yield
    workflow_runtime.set_saver(None)


@pytest.fixture
def owner_headers() -> dict[str, str]:
    token = create_access_token(str(OWNER_ID))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_db():
    """get_db 覆盖：owner 恒通过成员校验（Project 查询返回本项目，其余实体查无）."""

    def _execute(*args, **kwargs):
        stmt = args[0] if args else kwargs.get("statement")
        descriptions = getattr(stmt, "column_descriptions", None) or []
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Project:
            return _result(_owned_project())
        if entity is None:
            # 聚合查询（阶段 H 导出门禁：未确认废标条款计数）返回 0 放行
            agg = MagicMock()
            agg.scalar.return_value = 0
            return agg
        return _result(None)

    session = AsyncMock()
    session.execute.side_effect = _execute
    session.add = MagicMock()  # audit.record 同步调用 add，不能用 AsyncMock
    app.dependency_overrides[get_db] = lambda: session
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def mock_node_deps(monkeypatch):
    """mock 节点外部依赖，LLM 走 mock 模式."""

    async def fake_publish_event(_project_id: str, _event: dict) -> None:
        pass

    def fake_session_factory():
        return _node_db()

    async def fake_get_embedding(_text: str):
        return []

    async def fake_retrieve_similar(**kwargs):
        return []

    async def fake_export_to_word(**kwargs) -> str:
        return FAKE_EXPORT_KEY

    async def fake_call_llm_with_schema(**kwargs) -> dict:
        return {
            "chapters": [
                {"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]},
                {"chapter_no": "2", "title": "技术方案", "sections": ["架构", "实现"]},
            ]
        }

    monkeypatch.setattr(settings, "llm_mock", True)
    monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
    monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_call_llm_with_schema)
    monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.document.export_service.export_to_word", fake_export_to_word)


async def _get_status(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/workflow/status", headers=headers)
    assert resp.status_code == 200
    return resp.json()["data"]


async def _wait_status(
    client: AsyncClient, headers: dict[str, str], predicate: Callable[[dict], bool]
) -> dict:
    """轮询 status 直到断言条件成立（后台任务推进图执行）."""
    deadline = asyncio.get_event_loop().time() + 10
    while True:
        status = await _get_status(client, headers)
        if predicate(status):
            return status
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"等待工作流状态超时，当前: {status}")
        await asyncio.sleep(0.05)


def _interrupt_type(status: dict) -> str:
    return (status.get("interrupt") or {}).get("type", "")


class TestConfirmReview:
    """review HITL 恢复端点：approved → 导出 / feedback → 重写后复审."""

    async def _advance_to_review(self, client: AsyncClient, headers: dict[str, str]) -> None:
        """start → confirm-score-points → confirm-outline（自动生成模式），推进到 review interrupt."""
        resp = await client.post(f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=headers)
        assert resp.status_code == 200
        await _wait_status(client, headers, lambda d: _interrupt_type(d) == "confirm_score_points")

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-score-points", headers=headers
        )
        assert resp.status_code == 200
        await _wait_status(client, headers, lambda d: _interrupt_type(d) == "confirm_outline")

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=headers,
            json={"start_generation": True},
        )
        assert resp.status_code == 200
        await _wait_status(client, headers, lambda d: _interrupt_type(d) == "review_request")

    @pytest.mark.asyncio
    async def test_confirm_review_approved_advances_to_export(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps
    ) -> None:
        """approved → 图推进到 export 节点自动导出完成."""
        await self._advance_to_review(client, owner_headers)

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "approved"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "confirmed"
        assert data["next_phase"] == "export"

        status = await _wait_status(client, owner_headers, lambda d: d["export_status"] == "done")
        assert status["phase"] == "done"
        assert status["export_storage_key"] == FAKE_EXPORT_KEY

    @pytest.mark.asyncio
    async def test_confirm_review_feedback_rewrites_and_reinterrupts(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps, monkeypatch
    ) -> None:
        """feedback → rewrite → integrate → review 再次 interrupt，指定章节被重写."""
        rewrite_marker = "# 审阅反馈重写后的章节内容\n"

        async def fake_rewrite_chapter(**kwargs) -> str:
            return rewrite_marker * 20

        monkeypatch.setattr("app.services.proposal.review_service.rewrite_chapter", fake_rewrite_chapter)

        await self._advance_to_review(client, owner_headers)

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "feedback", "feedback": {"1": "补充项目范围说明"}},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["next_phase"] == "rewrite"

        # 重写后再次停在 review interrupt，且章节 1 已被重写
        status = await _wait_status(
            client,
            owner_headers,
            lambda d: (
                _interrupt_type(d) == "review_request"
                and rewrite_marker in d["chapters"].get("1", "")
            ),
        )
        assert "2" in status["chapters"], "未反馈章节不受影响"

        # 复审通过 → 导出完成
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "approved"},
        )
        assert resp.status_code == 200
        status = await _wait_status(client, owner_headers, lambda d: d["export_status"] == "done")
        assert status["phase"] == "done"

    @pytest.mark.asyncio
    async def test_confirm_review_invalid_action_rejected(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps
    ) -> None:
        """非法 action 被参数校验拒绝（422）."""
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "reject-all"},
        )
        assert resp.status_code == 422


class TestWorkflowApiEndToEnd:
    """start → confirm-score-points → confirm-outline → rewrite → export 全链路."""

    @pytest.mark.asyncio
    async def test_full_hitl_flow(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps
    ) -> None:
        # ── 1. start：后台执行，停在评分点 interrupt ──
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=owner_headers
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["workflow_id"] == str(PROJECT_ID)

        status = await _wait_status(
            client, owner_headers, lambda d: _interrupt_type(d) == "confirm_score_points"
        )
        assert status["phase"] == "confirm"
        assert status["progress"] > 0.0
        assert status["score_points"], "parse 节点从 DB 产出评分点，非硬编码空值"

        # ── 2. confirm-score-points：推进到大纲 interrupt ──
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-score-points",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "confirmed"

        status = await _wait_status(
            client, owner_headers, lambda d: _interrupt_type(d) == "confirm_outline"
        )
        assert status["outline"], "mock 模式大纲已生成"

        # ── 3. confirm-outline（自动生成模式 + 携带修改后的大纲）→ 进入生成 → 停在审阅 ──
        modified_outline = [{"chapter_no": "9", "title": "定制章节", "sections": ["小节A"]}]
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
            json={"outline": modified_outline, "start_generation": True},
        )
        assert resp.status_code == 200

        status = await _wait_status(
            client, owner_headers, lambda d: _interrupt_type(d) == "review_request"
        )
        assert status["outline"] == modified_outline, "修改后的大纲应写入 state"
        assert "9" in status["chapters"], "按修改后大纲生成章节"

        # ── 4. rewrite-chapter：取 state 原文重写并回写 ──
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/rewrite-chapter",
            headers=owner_headers,
            params={"chapter_no": "9", "comment": "补充项目范围说明"},
        )
        assert resp.status_code == 200
        rewritten = resp.json()["data"]
        assert rewritten["chapter_no"] == "9"
        assert rewritten["content"], "mock LLM 返回重写内容"

        status = await _wait_status(
            client, owner_headers, lambda d: d["chapters"].get("9") == rewritten["content"]
        )
        assert status["chapters"]["9"] == rewritten["content"]

        # ── 5. export：复用 export 逻辑，返回下载信息 ──
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/workflow/export", headers=owner_headers
        )
        assert resp.status_code == 200
        exported = resp.json()["data"]
        assert exported["export_status"] == "done"
        assert exported["export_storage_key"] == FAKE_EXPORT_KEY

        status = await _wait_status(client, owner_headers, lambda d: d["export_status"] == "done")
        assert status["export_storage_key"] == FAKE_EXPORT_KEY

    @pytest.mark.asyncio
    async def test_status_before_start_is_init(
        self, client, runtime_memory, owner_db, owner_headers
    ) -> None:
        """未启动时 status 返回 init 初始值."""
        status = await _get_status(client, owner_headers)
        assert status["phase"] == "init"
        assert status["progress"] == 0.0
        assert status["interrupt"] is None

    @pytest.mark.asyncio
    async def test_rewrite_missing_chapter_returns_error(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps
    ) -> None:
        """章节未生成时重写返回业务错误码."""
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/rewrite-chapter",
            headers=owner_headers,
            params={"chapter_no": "1", "comment": "意见"},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_export_before_chapters_returns_error(
        self, client, runtime_memory, owner_db, owner_headers
    ) -> None:
        """章节未生成时导出返回业务错误码."""
        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/workflow/export", headers=owner_headers
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4005


class TestResumeValidation:
    """confirm 端点 resume 前校验 pending interrupt（无/类型不匹配 → 4009，不污染 state）."""

    @pytest.mark.asyncio
    async def test_confirm_review_without_interrupt_rejected(
        self, client, runtime_memory, owner_db, owner_headers
    ) -> None:
        """无 pending interrupt → 4009，state.error 不被污染."""
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "approved"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4009

        status = await _get_status(client, owner_headers)
        assert status["error"] == ""
        assert status["interrupt"] is None

    @pytest.mark.asyncio
    async def test_confirm_review_with_mismatched_interrupt_rejected(
        self, client, runtime_memory, owner_db, owner_headers, mock_node_deps
    ) -> None:
        """停在评分点 interrupt 时 confirm-review 被拒（4009），原 interrupt 不变."""
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=owner_headers
        )
        assert resp.status_code == 200
        await _wait_status(
            client, owner_headers, lambda d: _interrupt_type(d) == "confirm_score_points"
        )

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-review",
            headers=owner_headers,
            json={"action": "approved"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4009

        status = await _get_status(client, owner_headers)
        assert _interrupt_type(status) == "confirm_score_points", "挂起 interrupt 不应变化"
        assert status["error"] == ""

    @pytest.mark.asyncio
    async def test_confirm_outline_without_interrupt_rejected(
        self, client, runtime_memory, owner_db, owner_headers
    ) -> None:
        """无 pending interrupt → confirm-outline 被拒（4009），大纲不回写."""
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
            json={"outline": [{"chapter_no": "1", "title": "定制章节", "sections": ["小节A"]}]},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4009

        status = await _get_status(client, owner_headers)
        assert status["error"] == ""
        assert status["outline"] == [], "拒绝时不应回写大纲"

    @pytest.mark.asyncio
    async def test_duplicate_start_rejected_by_api(
        self, client, runtime_memory, owner_db, owner_headers, monkeypatch
    ) -> None:
        """工作流在途时第二次 start 被拒（4009），任务结束后在途集合清理."""
        release = asyncio.Event()
        finished = asyncio.Event()

        async def hang(project_id, user_id):
            await release.wait()
            finished.set()
            return {}

        monkeypatch.setattr(workflow_runtime, "run_workflow", hang)

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=owner_headers
        )
        assert resp.status_code == 200

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=owner_headers
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 4009

        # 释放在途任务并等待在途集合清理，避免影响后续用例
        release.set()
        await asyncio.wait_for(finished.wait(), 5)
        deadline = asyncio.get_event_loop().time() + 5
        while str(PROJECT_ID) in workflow_runtime._running:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("在途执行集合未随任务结束清理")
            await asyncio.sleep(0.02)


class TestConfirmOutlineMountedDocs:
    """confirm-outline 资料库挂载配置（mounted_doc_ids 经 resume payload 传递）."""

    def _patch_runtime(self, monkeypatch) -> dict:
        """mock 工作流运行器，捕获 resume payload（编辑/挂载配置不再走 update_state）."""
        from app.api import workflow as workflow_api

        captured: dict = {}

        async def fake_ensure(_project_id, _interrupt_type) -> None:
            pass

        def fake_resume(_project_id, resume_value):
            captured["resume"] = resume_value
            return MagicMock()

        monkeypatch.setattr(workflow_api.workflow_runtime, "ensure_pending_interrupt", fake_ensure)
        monkeypatch.setattr(
            workflow_api.workflow_runtime, "resume_workflow_in_background", fake_resume
        )
        return captured

    @pytest.mark.asyncio
    async def test_mounted_doc_ids_written_to_state(
        self, client, owner_headers, owner_db, monkeypatch
    ) -> None:
        """携带 mounted_doc_ids → 以字符串化 UUID 列表进入 resume payload（节点写入 state）."""
        captured = self._patch_runtime(monkeypatch)
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
            json={"mounted_doc_ids": doc_ids},
        )
        assert resp.status_code == 200
        assert captured["resume"]["mounted_doc_ids"] == doc_ids

    @pytest.mark.asyncio
    async def test_without_mounted_doc_ids_keeps_default(
        self, client, owner_headers, owner_db, monkeypatch
    ) -> None:
        """不携带 mounted_doc_ids → resume payload 不含该键（保持项目全量检索）."""
        captured = self._patch_runtime(monkeypatch)

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert "mounted_doc_ids" not in captured["resume"]
        assert captured["resume"]["confirmed"] is True

    @pytest.mark.asyncio
    async def test_empty_mounted_doc_ids_means_mount_none(
        self, client, owner_headers, owner_db, monkeypatch
    ) -> None:
        """空列表 = 明确不挂载任何资料（生成不使用 RAG 素材）."""
        captured = self._patch_runtime(monkeypatch)

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
            json={"mounted_doc_ids": []},
        )
        assert resp.status_code == 200
        assert captured["resume"]["mounted_doc_ids"] == []

    @pytest.mark.asyncio
    async def test_confirm_outline_forbidden_for_non_owner(self, client, monkeypatch) -> None:
        """非 owner 确认大纲 → 403（确认权收紧为仅 owner）."""
        self._patch_runtime(monkeypatch)
        session = AsyncMock()

        def _execute(stmt, *a, **k):
            return _result(_owned_project())

        session.execute.side_effect = _execute
        app.dependency_overrides[get_db] = lambda: session
        try:
            headers = {"Authorization": f"Bearer {create_access_token(str(uuid.uuid4()))}"}
            resp = await client.post(
                f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
                headers=headers,
                json={},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestOutlineDraft:
    """大纲二次编辑草稿端点：保存/读取/清除（读成员可读，写仅 owner，留审计）."""

    DRAFT_OUTLINE: ClassVar[list[dict]] = [
        {
            "chapter_no": "1",
            "title": "项目概述",
            "sections": [{"title": "背景", "children": [{"title": "政策"}]}],
            "covered_clauses": ["4.1"],
        }
    ]

    def _skeleton(self) -> ProposalSkeleton:
        # 单例：PUT/GET 共享同一对象（模拟真实行，写入对后续读取可见）
        if getattr(self, "_skeleton_row", None) is None:
            skeleton = ProposalSkeleton(project_id=PROJECT_ID, tree=[])
            skeleton.draft = {"outline": self.DRAFT_OUTLINE, "mounted_doc_ids": None}
            self._skeleton_row = skeleton
        return self._skeleton_row

    @pytest.fixture
    def draft_db(self):
        """get_db 覆盖：Project 返回 owner 项目，ProposalSkeleton 返回预置行."""
        session = AsyncMock()

        def _execute(stmt, *a, **k):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Project:
                return _result(_owned_project())
            if entity is ProjectMember:
                return _result(None)  # 非成员分支：成员表查无此人 → 403
            return _result(self._skeleton())

        session.execute.side_effect = _execute
        session.add = MagicMock()
        app.dependency_overrides[get_db] = lambda: session
        yield session
        app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_save_and_read_draft(self, client, owner_headers, draft_db) -> None:
        """PUT 保存草稿 → GET 读回（含编辑产物与挂载配置）."""
        resp = await client.put(
            f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft",
            headers=owner_headers,
            json={
                "outline": self.DRAFT_OUTLINE,
                "mounted_doc_ids": [str(uuid.uuid4())],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["saved"] is True

        resp = await client.get(
            f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["outline"][0]["title"] == "项目概述"
        assert data["outline"][0]["sections"][0]["children"][0]["title"] == "政策"
        assert data["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_clear_draft(self, client, owner_headers, draft_db) -> None:
        """DELETE 清除草稿（确认成功后前端调用，幂等）."""
        resp = await client.delete(
            f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["cleared"] is True

    @pytest.mark.asyncio
    async def test_non_member_forbidden(self, client, draft_db) -> None:
        """非成员读写草稿均 403."""
        other_token = create_access_token(str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {other_token}"}
        resp = await client.put(
            f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft",
            headers=headers,
            json={"outline": self.DRAFT_OUTLINE},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_owner_member_write_draft_forbidden(self, client, draft_db) -> None:
        """项目成员但非 owner 写草稿 → 403（大纲编辑权收紧为仅 owner）."""
        from app.models.project import ProjectMember

        member_id = uuid.uuid4()
        # 草稿 DB 覆盖的 Project owner = OWNER_ID；成员表命中 → 成员非 owner
        session = AsyncMock()

        def _execute(stmt, *a, **k):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Project:
                return _result(_owned_project())
            if entity is ProjectMember:
                return _result(ProjectMember(project_id=PROJECT_ID, user_id=member_id))
            return _result(self._skeleton())

        session.execute.side_effect = _execute
        app.dependency_overrides[get_db] = lambda: session
        try:
            headers = {"Authorization": f"Bearer {create_access_token(str(member_id))}"}
            for method, body in (
                (client.put, {"outline": self.DRAFT_OUTLINE}),
                (client.delete, None),
            ):
                kwargs = {"headers": headers}
                if body is not None:
                    kwargs["json"] = body
                resp = await method(
                    f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft", **kwargs
                )
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_get_audit_on_save(self, client, owner_headers, draft_db) -> None:
        """保存草稿留审计（workflow.outline_draft_save）."""
        resp = await client.put(
            f"/api/v1/projects/{PROJECT_ID}/workflow/outline-draft",
            headers=owner_headers,
            json={"outline": self.DRAFT_OUTLINE},
        )
        assert resp.status_code == 200
        actions = [call.args[0].action for call in draft_db.add.call_args_list]
        assert "workflow.outline_draft_save" in actions
