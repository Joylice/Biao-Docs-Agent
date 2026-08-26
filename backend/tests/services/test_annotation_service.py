"""章节批注服务单测 — 阶段 E5（批注 CRUD：查询/新增/编辑/删除 + 作者/owner 判定）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.project import Project
from app.models.proposal import ChapterAnnotation
from app.services.project import annotation_service

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
AUTHOR_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _ann(content: str = "请补充案例", created_by: uuid.UUID = AUTHOR_ID) -> ChapterAnnotation:
    return ChapterAnnotation(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no="1",
        content=content,
        created_by=created_by,
    )


def _project(owner_id: uuid.UUID = OWNER_ID) -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=owner_id, status="active")


class TestListAnnotations:
    @pytest.mark.asyncio
    async def test_serialized_with_author_name(self) -> None:
        """时间正序 + 作者名 JOIN；created_by_name 缺失时空串由调用方兜底."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows_result([(_ann(), "张三")]))
        items = await annotation_service.list_annotations(db, PROJECT_ID, "1")
        assert len(items) == 1
        assert items[0]["content"] == "请补充案例"
        assert items[0]["created_by_name"] == "张三"
        assert items[0]["created_by"] == str(AUTHOR_ID)
        stmt = str(db.execute.await_args.args[0])
        assert "ASC" in stmt  # 时间正序


class TestCreateAnnotation:
    @pytest.mark.asyncio
    async def test_creates_with_stripped_content(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        data = await annotation_service.create_annotation(
            db, PROJECT_ID, "1", " 请补充实施案例 ", OWNER_ID
        )
        db.add.assert_called_once()
        db.flush.assert_awaited()
        db.refresh.assert_awaited()
        assert data["content"] == "请补充实施案例"
        assert data["chapter_no"] == "1"
        assert data["created_by"] == str(OWNER_ID)


class TestUpdateAnnotation:
    @pytest.mark.asyncio
    async def test_unknown_annotation_404(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(NotFoundError):
            await annotation_service.update_annotation(
                db, PROJECT_ID, "1", uuid.uuid4(), "x", OWNER_ID
            )

    @pytest.mark.asyncio
    async def test_author_updates(self) -> None:
        """作者本人编辑：内容更新 + flush/refresh + 序列化返回."""
        ann = _ann(created_by=OWNER_ID)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(ann))
        data = await annotation_service.update_annotation(
            db, PROJECT_ID, "1", ann.id, " 修改后的意见 ", OWNER_ID
        )
        assert ann.content == "修改后的意见"
        assert data["content"] == "修改后的意见"
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_author_non_owner_forbidden(self) -> None:
        """非作者且非项目 owner → ForbiddenError（查询 Project 判定 owner）."""
        ann = _ann(created_by=AUTHOR_ID)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result(ann), _result(_project(OWNER_ID))])
        with pytest.raises(ForbiddenError):
            await annotation_service.update_annotation(db, PROJECT_ID, "1", ann.id, "x", OTHER_ID)

    @pytest.mark.asyncio
    async def test_project_owner_updates_others_annotation(self) -> None:
        """项目 owner 可编辑他人批注."""
        ann = _ann(created_by=AUTHOR_ID)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result(ann), _result(_project(OWNER_ID))])
        data = await annotation_service.update_annotation(
            db, PROJECT_ID, "1", ann.id, "owner 修改", OWNER_ID
        )
        assert data["content"] == "owner 修改"


class TestDeleteAnnotation:
    @pytest.mark.asyncio
    async def test_author_deletes(self) -> None:
        ann = _ann(created_by=OWNER_ID)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(ann))
        ann_id = await annotation_service.delete_annotation(db, PROJECT_ID, "1", ann.id, OWNER_ID)
        assert ann_id == str(ann.id)
        db.delete.assert_awaited_once_with(ann)

    @pytest.mark.asyncio
    async def test_unknown_annotation_404(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with pytest.raises(NotFoundError):
            await annotation_service.delete_annotation(db, PROJECT_ID, "1", uuid.uuid4(), OWNER_ID)

    @pytest.mark.asyncio
    async def test_non_author_non_owner_forbidden(self) -> None:
        ann = _ann(created_by=AUTHOR_ID)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_result(ann), _result(_project(OWNER_ID))])
        with pytest.raises(ForbiddenError):
            await annotation_service.delete_annotation(db, PROJECT_ID, "1", ann.id, OTHER_ID)
        db.delete.assert_not_awaited()
