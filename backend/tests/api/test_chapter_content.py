"""章节内容读写 API 测试 — GET/PUT /projects/{pid}/chapters/{chapter_no}/content.

覆盖：
- GET：成员读取（owner 直通/普通成员）、content_html 可空回读、非成员 403、无分工 4004
- PUT：成员保存双字段 + 审计 chapter.content_update + commit、content_html 可空、
  非成员 403、无分工 4004、content 空串合法（已清空状态）
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAssignment

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _assignment(content: str = "", content_html: str | None = None) -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no="1",
        title="项目概述",
        assignee_id=MEMBER_ID,
        assigned_by=OWNER_ID,
        status="in_progress",
        content=content,
        content_html=content_html,
    )


@pytest.fixture
def override_db() -> Generator:
    def _override(results: list) -> AsyncMock:
        session = AsyncMock()
        session.add = MagicMock()
        session.execute.side_effect = results
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/chapters/1/content"


class TestGetChapterContent:
    @pytest.mark.asyncio
    async def test_owner_reads(self, client: AsyncClient, override_db) -> None:
        """项目 owner 读取章节内容（Markdown + HTML 双字段）."""
        override_db(
            [
                _result(_project()),  # 成员校验（owner 直通）
                _result(_assignment("# 正文", "<p>正文</p>")),
            ]
        )
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["content"] == "# 正文"
        assert data["content_html"] == "<p>正文</p>"

    @pytest.mark.asyncio
    async def test_member_reads(self, client: AsyncClient, override_db) -> None:
        """普通项目成员读取（成员表命中）."""
        override_db(
            [
                _result(_project()),
                _result(_member_row()),  # 非 owner → 成员表校验
                _result(_assignment("正文")),
            ]
        )
        resp = await client.get(_url(), headers=_headers(MEMBER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["content"] == "正文"

    @pytest.mark.asyncio
    async def test_content_html_nullable(self, client: AsyncClient, override_db) -> None:
        """content_html 可空：未保存过 HTML 时回读 null."""
        override_db([_result(_project()), _result(_assignment("正文", None))])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        assert resp.json()["data"]["content_html"] is None

    @pytest.mark.asyncio
    async def test_non_member_403(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.get(_url(), headers=_headers(uuid.uuid4()))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_chapter_not_found_4004(self, client: AsyncClient, override_db) -> None:
        """chapter_no 无对应分工记录 → BizError 4004（HTTP 404）."""
        override_db([_result(_project()), _result(None)])
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004


class TestSaveChapterContent:
    @pytest.mark.asyncio
    async def test_member_saves_with_audit_and_commit(
        self, client: AsyncClient, override_db
    ) -> None:
        """成员保存：双字段落库 + 审计 chapter.content_update + commit."""
        assignment = _assignment()
        session = override_db([_result(_project()), _result(assignment)])
        resp = await client.put(
            _url(),
            json={"content": "# 新正文", "content_html": "<p>新正文</p>"},
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 200
        assert assignment.content == "# 新正文"
        assert assignment.content_html == "<p>新正文</p>"
        actions = [
            c.args[0].action for c in session.add.call_args_list if hasattr(c.args[0], "action")
        ]
        assert "chapter.content_update" in actions
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_save_html_optional(self, client: AsyncClient, override_db) -> None:
        """content_html 缺省 → None 落库并回读."""
        assignment = _assignment("旧", "<p>旧</p>")
        override_db([_result(_project()), _result(assignment)])
        resp = await client.put(_url(), json={"content": "新正文"}, headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        assert assignment.content == "新正文"
        assert assignment.content_html is None
        assert resp.json()["data"]["content_html"] is None

    @pytest.mark.asyncio
    async def test_non_member_save_403(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.put(_url(), json={"content": "x"}, headers=_headers(uuid.uuid4()))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_save_chapter_not_found_4004(self, client: AsyncClient, override_db) -> None:
        session = override_db([_result(_project()), _result(None)])
        resp = await client.put(_url(), json={"content": "x"}, headers=_headers(OWNER_ID))
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_content_ok(self, client: AsyncClient, override_db) -> None:
        """content 空串合法：清空编辑器后保存应 200 落库（防止自动保存 422 死循环）."""
        assignment = _assignment("旧正文", "<p>旧</p>")
        session = override_db([_result(_project()), _result(assignment)])
        resp = await client.put(_url(), json={"content": ""}, headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        assert assignment.content == ""
        session.commit.assert_awaited()


# ── POST /chapters/{no}/assist-selection（2026-08-26 选区 AI）──


class TestAssistSelection:
    """选区 AI 处理：项目成员可调（不依赖 assignee）、不落库、mock 降级返回原文."""

    @staticmethod
    def _url() -> str:
        return f"/api/v1/projects/{PROJECT_ID}/chapters/1/assist-selection"

    @pytest.mark.asyncio
    async def test_member_polish_success(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """项目成员润色选区：mock call_llm_text 返回处理结果 → 200 content."""
        override_db([_result(_project()), _result(_member_row()), _result(_assignment())])
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        from app.services.llm import llm_service

        async def fake_call_llm_text(system_prompt, user_prompt, temperature=0.7, mock=None):
            assert "润色" in system_prompt
            assert "原始文字" in user_prompt
            return "润色后的文字"

        monkeypatch.setattr(llm_service, "call_llm_text", fake_call_llm_text)

        resp = await client.post(
            self._url(),
            json={"text": "原始文字", "action": "polish"},
            headers=_headers(MEMBER_ID),
        )

        assert resp.status_code == 200
        assert resp.json()["data"] == {"content": "润色后的文字"}

    @pytest.mark.asyncio
    async def test_member_can_use_without_being_assignee(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """关键契约：非 assignee 的项目成员也可调用（区别于 assist-generate 的 assignee 限制）."""
        override_db([_result(_project()), _result(_member_row()), _result(_assignment())])
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=False)
        )
        from app.services.llm import llm_service

        async def fake_call_llm_text(system_prompt, user_prompt, temperature=0.7, mock=None):
            return "翻译结果"

        monkeypatch.setattr(llm_service, "call_llm_text", fake_call_llm_text)

        resp = await client.post(
            self._url(),
            json={"text": "hello world", "action": "translate"},
            headers=_headers(MEMBER_ID),
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["content"] == "翻译结果"

    @pytest.mark.asyncio
    async def test_non_member_403(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.post(
            self._url(),
            json={"text": "x", "action": "polish"},
            headers=_headers(uuid.uuid4()),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_chapter_not_found_4004(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.post(
            self._url(),
            json={"text": "x", "action": "polish"},
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_invalid_action_422(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(_assignment())])
        resp = await client.post(
            self._url(),
            json={"text": "x", "action": "summarize"},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_mock_mode_returns_original_text(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """mock 模式降级：返回原文，避免占位文本污染文档."""
        override_db([_result(_project()), _result(_member_row()), _result(_assignment())])
        monkeypatch.setattr(
            "app.services.infra.settings_service.is_mock_enabled", AsyncMock(return_value=True)
        )
        from app.services.llm import llm_service

        async def boom(*args, **kwargs):
            raise AssertionError("mock 模式下不应调用 LLM")

        monkeypatch.setattr(llm_service, "call_llm_text", boom)

        resp = await client.post(
            self._url(),
            json={"text": "原始文字", "action": "polish"},
            headers=_headers(MEMBER_ID),
        )

        assert resp.status_code == 200
        assert resp.json()["data"] == {"content": "原始文字"}
