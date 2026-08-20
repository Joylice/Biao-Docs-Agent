"""章节级批注 API 测试 — 阶段 E5（chapters/{no}/annotations CRUD + 权限）."""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

import app.api.annotations as annotations_api
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAnnotation

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
AUTHOR_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _ann(
    content: str = "请补充案例", created_by: uuid.UUID = AUTHOR_ID
) -> ChapterAnnotation:
    return ChapterAnnotation(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no="1",
        content=content,
        created_by=created_by,
    )


@pytest.fixture
def override_db() -> Generator:
    def _override(results: list) -> AsyncMock:
        session = AsyncMock()
        session.add = MagicMock()
        session.delete = MagicMock()
        session.execute.side_effect = results
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _url() -> str:
    return f"/api/v1/projects/{PROJECT_ID}/chapters/1/annotations"


class TestListChapterAnnotations:
    @pytest.mark.asyncio
    async def test_member_reads(self, client: AsyncClient, override_db) -> None:
        """项目成员读取章节批注（时间正序，含作者名）."""
        override_db(
            [
                _result(_project()),  # 成员校验（owner 直通）
                _rows_result([(_ann(), "张三")]),
            ]
        )
        resp = await client.get(_url(), headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["content"] == "请补充案例"
        assert items[0]["created_by_name"] == "张三"

    @pytest.mark.asyncio
    async def test_non_member_403(self, client: AsyncClient, override_db) -> None:
        override_db([_result(_project()), _result(None)])
        resp = await client.get(_url(), headers=_headers(uuid.uuid4()))
        assert resp.status_code == 403


class TestCreateChapterAnnotation:
    @pytest.mark.asyncio
    async def test_editable_creates(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """可编辑者新增批注：内容去空格 + 审计 annotation.create + commit."""
        session = override_db([_result(_project())])
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=True)
        )
        resp = await client.post(
            _url(), json={"content": " 请补充实施案例 "}, headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["content"] == "请补充实施案例"
        assert data["chapter_no"] == "1"
        actions = [
            c.args[0].action for c in session.add.call_args_list
            if hasattr(c.args[0], "action")
        ]
        assert "annotation.create" in actions
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_not_editable_403(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """非负责人/非 owner 批注 403（复用 check_chapter_editable 口径）."""
        override_db([_result(_project())])
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=False)
        )
        resp = await client.post(
            _url(), json={"content": "x"}, headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 403


class TestUpdateChapterAnnotation:
    @pytest.mark.asyncio
    async def test_author_updates(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """作者本人编辑批注."""
        ann = _ann(created_by=OWNER_ID)
        session = override_db([_result(_project()), _result(ann)])
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=True)
        )
        resp = await client.put(
            f"{_url()}/{ann.id}",
            json={"content": "修改后的意见"},
            headers=_headers(OWNER_ID),
        )
        assert resp.status_code == 200
        assert ann.content == "修改后的意见"
        actions = [
            c.args[0].action for c in session.add.call_args_list
            if hasattr(c.args[0], "action")
        ]
        assert "annotation.update" in actions
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_author_non_owner_403(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """非作者且非 owner 编辑 403."""
        ann = _ann(created_by=AUTHOR_ID)
        override_db(
            [
                _result(_project()),  # 成员校验
                _result(_member_row()),
                _result(ann),
                _result(_project()),  # owner 判定
            ]
        )
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=True)
        )
        resp = await client.put(
            f"{_url()}/{ann.id}",
            json={"content": "x"},
            headers=_headers(MEMBER_ID),
        )
        assert resp.status_code == 403


class TestDeleteChapterAnnotation:
    @pytest.mark.asyncio
    async def test_author_deletes(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """作者删除批注 + 审计 annotation.delete."""
        ann = _ann(created_by=OWNER_ID)
        session = override_db([_result(_project()), _result(ann)])
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=True)
        )
        resp = await client.delete(f"{_url()}/{ann.id}", headers=_headers(OWNER_ID))
        assert resp.status_code == 200
        session.delete.assert_called_once_with(ann)
        actions = [
            c.args[0].action for c in session.add.call_args_list
            if hasattr(c.args[0], "action")
        ]
        assert "annotation.delete" in actions
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_unknown_annotation_404(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        override_db([_result(_project()), _result(None)])
        monkeypatch.setattr(
            annotations_api, "check_chapter_editable", AsyncMock(return_value=True)
        )
        resp = await client.delete(
            f"{_url()}/{uuid.uuid4()}", headers=_headers(OWNER_ID)
        )
        assert resp.status_code == 404
