"""工作流 API 功能测试 — InMemorySaver + LLM mock 驱动真实图（API → runtime → graph）.

parse 节点的数据经 monkeypatch nodes.async_session_factory 注入 FakeDB
（与 tests/agents/test_graph.py 同风格）；API 层的成员校验/审计经
dependency_overrides[get_db] 注入 mock 会话（与 test_authorization.py 同风格）。
"""

import asyncio
import uuid
from collections.abc import Callable
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
from app.models.project import Project
from app.services import workflow_runtime
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
    """get_db 覆盖：owner 恒通过成员校验（execute 始终返回本项目）."""
    session = AsyncMock()
    session.execute.side_effect = lambda *a, **k: _result(_owned_project())
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
    monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", fake_call_llm_with_schema)
    monkeypatch.setattr("app.services.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.export_service.export_to_word", fake_export_to_word)


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
        """start → confirm-score-points → confirm-outline，推进到 review interrupt."""
        resp = await client.post(f"/api/v1/projects/{PROJECT_ID}/workflow/start", headers=headers)
        assert resp.status_code == 200
        await _wait_status(client, headers, lambda d: _interrupt_type(d) == "confirm_score_points")

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-score-points", headers=headers
        )
        assert resp.status_code == 200
        await _wait_status(client, headers, lambda d: _interrupt_type(d) == "confirm_outline")

        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline", headers=headers
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

        monkeypatch.setattr("app.services.review_service.rewrite_chapter", fake_rewrite_chapter)

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

        # ── 3. confirm-outline（携带修改后的大纲）→ 进入生成 → 停在审阅 ──
        modified_outline = [{"chapter_no": "9", "title": "定制章节", "sections": ["小节A"]}]
        resp = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/workflow/confirm-outline",
            headers=owner_headers,
            json={"outline": modified_outline},
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
