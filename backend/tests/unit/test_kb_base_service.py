"""kb_base_service 批次 1b 新增函数单测（api/kb_bases.py / api/kb.py 残余直查下沉）.

覆盖行为等价：
- get_base_or_404：不存在 → NotFoundError(知识库不存在)
- get_base_for_upload：库不存在 4004；他人个人库 ForbiddenError；本人库放行
- get_project_name：项目不存在 → None
- update_base_fields：空白名称 4000；description 去空白归 None；changed 清单
- check_base_readable：他人个人库/无项目归属项目库 → NotFoundError；公司库放行
- delete_base：素材与库逐条 delete，不 commit
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError, ForbiddenError, NotFoundError
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project
from app.services import kb_base_service

USER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _base(
    scope: str,
    name: str,
    *,
    owner_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    base = KnowledgeBase(
        id=uuid.uuid4(),
        project_id=project_id,
        owner_id=owner_id,
        scope=scope,
        name=name,
        description=None,
    )
    base.created_at = datetime.now(UTC)
    return base


def _scalar_session(scalar: object) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    session.execute.return_value = result
    return session


class TestGetBaseOr404:
    async def test_missing_raises_not_found(self) -> None:
        session = _scalar_session(None)
        with pytest.raises(NotFoundError) as exc:
            await kb_base_service.get_base_or_404(session, uuid.uuid4())
        assert exc.value.code == 4004
        assert exc.value.message == "知识库不存在"

    async def test_returns_base(self) -> None:
        base = _base("personal", "我的库", owner_id=USER_ID)
        session = _scalar_session(base)
        result = await kb_base_service.get_base_or_404(session, base.id)
        assert result is base


class TestGetBaseForUpload:
    async def test_missing_base_raises_4004(self) -> None:
        session = _scalar_session(None)
        with pytest.raises(BizError) as exc:
            await kb_base_service.get_base_for_upload(session, uuid.uuid4(), USER_ID)
        assert exc.value.code == 4004
        assert exc.value.message == "知识库不存在"

    async def test_others_personal_base_forbidden(self) -> None:
        base = _base("personal", "他人库", owner_id=OTHER_ID)
        session = _scalar_session(base)
        with pytest.raises(ForbiddenError):
            await kb_base_service.get_base_for_upload(session, base.id, USER_ID)

    async def test_own_personal_base_ok(self) -> None:
        base = _base("personal", "我的库", owner_id=USER_ID)
        session = _scalar_session(base)
        result = await kb_base_service.get_base_for_upload(session, base.id, USER_ID)
        assert result is base


class TestGetProjectName:
    async def test_missing_project_returns_none(self) -> None:
        session = _scalar_session(None)
        assert await kb_base_service.get_project_name(session, PROJECT_ID) is None

    async def test_returns_name(self) -> None:
        project = Project(id=PROJECT_ID, name="河北高速投标", owner_id=USER_ID)
        session = _scalar_session(project)
        assert await kb_base_service.get_project_name(session, PROJECT_ID) == "河北高速投标"


class TestUpdateBaseFields:
    def test_blank_name_raises_4000(self) -> None:
        base = _base("personal", "旧名", owner_id=USER_ID)
        with pytest.raises(BizError) as exc:
            kb_base_service.update_base_fields(base, "   ", None)
        assert exc.value.code == 4000
        assert exc.value.message == "知识库名称不能为空"

    def test_applies_changes(self) -> None:
        base = _base("personal", "旧名", owner_id=USER_ID)
        changed = kb_base_service.update_base_fields(base, "新名", "  说明  ")
        assert base.name == "新名"
        assert base.description == "说明"
        assert changed == ["name", "description"]

    def test_blank_description_normalized_to_none(self) -> None:
        base = _base("personal", "旧名", owner_id=USER_ID)
        changed = kb_base_service.update_base_fields(base, None, "   ")
        assert base.description is None
        assert changed == ["description"]

    def test_no_fields_no_change(self) -> None:
        base = _base("personal", "旧名", owner_id=USER_ID)
        assert kb_base_service.update_base_fields(base, None, None) == []
        assert base.name == "旧名"


class TestCheckBaseReadable:
    async def test_others_personal_base_404(self) -> None:
        base = _base("personal", "他人库", owner_id=OTHER_ID)
        with pytest.raises(NotFoundError):
            await kb_base_service.check_base_readable(AsyncMock(), base, USER_ID)

    async def test_project_base_without_project_id_404(self) -> None:
        base = _base("project", "项目库", project_id=None)
        with pytest.raises(NotFoundError):
            await kb_base_service.check_base_readable(AsyncMock(), base, USER_ID)

    async def test_company_base_open(self) -> None:
        base = _base("company", "公司公共库")
        await kb_base_service.check_base_readable(AsyncMock(), base, USER_ID)

    async def test_project_base_owner_readable(self) -> None:
        """项目 owner 命中成员判定 → 放行."""
        base = _base("project", "项目库", project_id=PROJECT_ID)
        project = Project(id=PROJECT_ID, name="P", owner_id=USER_ID)
        session = _scalar_session(project)
        await kb_base_service.check_base_readable(session, base, USER_ID)


class TestDeleteBase:
    async def test_deletes_docs_then_base_no_commit(self) -> None:
        session = AsyncMock()
        base = _base("personal", "我的库", owner_id=USER_ID)
        docs = [
            Document(
                project_id=None,
                doc_type="kb_material",
                title=f"{i}.pdf",
                storage_key=f"global/{i}.pdf",
                status="indexed",
                kb_id=base.id,
            )
            for i in range(2)
        ]
        await kb_base_service.delete_base(session, base, docs)
        assert session.delete.await_count == 3
        session.commit.assert_not_awaited()


class TestBaseToDict:
    def test_fields_and_project_name(self) -> None:
        base = _base("project", "项目库", owner_id=USER_ID, project_id=PROJECT_ID)
        data = kb_base_service.base_to_dict(base, material_count=3, project_name="河北高速投标")
        assert data["id"] == str(base.id)
        assert data["name"] == "项目库"
        assert data["scope"] == "project"
        assert data["project_id"] == str(PROJECT_ID)
        assert data["project_name"] == "河北高速投标"
        assert data["owner_id"] == str(USER_ID)
        assert data["material_count"] == 3
        assert data["created_at"] == base.created_at.isoformat()

    def test_defaults(self) -> None:
        base = _base("personal", "我的库", owner_id=USER_ID)
        data = kb_base_service.base_to_dict(base)
        assert data["project_id"] is None
        assert data["project_name"] is None
        assert data["material_count"] == 0
