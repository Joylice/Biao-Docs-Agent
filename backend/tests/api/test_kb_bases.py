"""知识库 API 测试 — /kb-bases 可见性矩阵/建库权限/库内素材（阶段 1）.

覆盖：
- list：公司库全员可见 / 他人个人库不可见 / 项目库限成员（无上下文时列出所属项目库，阶段 3）
- create：personal 任意用户 / project 仅 owner / company 仅管理员 / 非法 scope / 同域重名
- patch/delete：写权限按 scope 判定，删库级联删素材
- materials：不可见库 404，公司库分页返回
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project
from app.models.user import User

USER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _full_result(rows: list) -> MagicMock:
    """兼容 scalar_one_or_none / scalars().all() / all() 三种取数方式的 mock 结果."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.scalars.return_value.all.return_value = rows
    result.all.return_value = rows
    return result


def _base(
    scope: str,
    name: str,
    *,
    owner_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    base_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    base = KnowledgeBase(
        id=base_id or uuid.uuid4(),
        project_id=project_id,
        owner_id=owner_id,
        scope=scope,
        name=name,
        description=None,
    )
    base.created_at = datetime.now(UTC)
    return base


def _user(user_id: uuid.UUID, email: str, role: str = "member") -> User:
    return User(id=user_id, email=email, password_hash="x", display_name="测试用户", role=role)


@pytest.fixture
def session_override() -> Generator:
    """按 execute 结果序列覆盖 get_db，用例结束清理."""

    def _override(results: list[MagicMock]) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = results
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(USER_ID))}"}


class TestListKbBases:
    """GET /kb-bases 可见性矩阵."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/kb-bases")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_company_base_visible_to_all(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """公司库全员可见（含素材数统计）."""
        base = _base("company", "公司公共库", base_id=uuid.uuid4())
        counts = MagicMock()
        counts.all.return_value = [(base.id, 3)]
        session_override([_full_result([base]), counts])
        resp = await client.get("/api/v1/kb-bases", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["name"] == "公司公共库"
        assert data["items"][0]["material_count"] == 3

    @pytest.mark.asyncio
    async def test_personal_base_only_owner_visible(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """他人个人库不可见，本人个人库可见."""
        mine = _base("personal", "我的库", owner_id=USER_ID)
        others = _base("personal", "他人库", owner_id=OTHER_ID)
        session_override([_full_result([mine, others]), _full_result([])])
        resp = await client.get("/api/v1/kb-bases", headers=headers)
        items = resp.json()["data"]["items"]
        assert [i["name"] for i in items] == ["我的库"]

    @pytest.mark.asyncio
    async def test_project_base_visible_to_member(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """带项目上下文且为项目 owner → 项目库可见."""
        base = _base("project", "项目库", project_id=PROJECT_ID)
        project = Project(id=PROJECT_ID, name="P", owner_id=USER_ID)
        session_override(
            [
                _full_result([base]),
                _full_result([]),
                _full_result([project]),  # 项目名批量
                _full_result([project]),  # 成员判定
            ]
        )
        resp = await client.get(
            "/api/v1/kb-bases", params={"project_id": str(PROJECT_ID)}, headers=headers
        )
        items = resp.json()["data"]["items"]
        assert [i["name"] for i in items] == ["项目库"]
        assert items[0]["project_name"] == "P"

    @pytest.mark.asyncio
    async def test_project_base_hidden_from_non_member(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """非成员（非 owner 且不在成员表）→ 项目库不可见."""
        base = _base("project", "项目库", project_id=PROJECT_ID)
        project = Project(id=PROJECT_ID, name="P", owner_id=OTHER_ID)
        session_override(
            [
                _full_result([base]),
                _full_result([]),
                _full_result([project]),  # 项目名批量
                _full_result([project]),
                _full_result([]),  # project_members 无记录
            ]
        )
        resp = await client.get(
            "/api/v1/kb-bases", params={"project_id": str(PROJECT_ID)}, headers=headers
        )
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_project_base_listed_without_context_for_member(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """无项目上下文（全局资料页）：成员可见所属项目库并带 project_name（阶段 3）."""
        base = _base("project", "项目库", project_id=PROJECT_ID)
        project = Project(id=PROJECT_ID, name="河北高速投标", owner_id=USER_ID)
        session_override(
            [
                _full_result([base]),
                _full_result([]),
                _full_result([project]),  # 项目名批量
                _full_result([project]),  # _is_project_member → owner 命中
            ]
        )
        resp = await client.get("/api/v1/kb-bases", headers=headers)
        items = resp.json()["data"]["items"]
        assert [i["name"] for i in items] == ["项目库"]
        assert items[0]["project_name"] == "河北高速投标"

    @pytest.mark.asyncio
    async def test_project_base_hidden_without_context_for_non_member(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """无项目上下文且非成员 → 项目库不出现（越权隔离）."""
        base = _base("project", "项目库", project_id=PROJECT_ID)
        project = Project(id=PROJECT_ID, name="P", owner_id=OTHER_ID)
        session_override(
            [
                _full_result([base]),
                _full_result([]),
                _full_result([project]),
                _full_result([project]),  # owner 非本人
                _full_result([]),  # project_members 无记录
            ]
        )
        resp = await client.get("/api/v1/kb-bases", headers=headers)
        assert resp.json()["data"]["items"] == []


class TestCreateKbBase:
    """POST /kb-bases 建库权限."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/kb-bases", json={"scope": "personal", "name": "x"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_personal_by_any_user(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """personal 任意登录用户可建（owner_id 记录本人）+ 审计."""
        session = session_override([_full_result([])])  # 重名查询无命中

        async def fake_refresh(obj):
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = obj.created_at or datetime.now(UTC)

        session.refresh.side_effect = fake_refresh
        resp = await client.post(
            "/api/v1/kb-bases",
            json={"scope": "personal", "name": "我的资料", "description": "个人积累"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["scope"] == "personal"
        assert data["owner_id"] == str(USER_ID)
        added = [c.args[0] for c in session.add.call_args_list]
        bases = [a for a in added if isinstance(a, KnowledgeBase)]
        assert bases and bases[0].owner_id == USER_ID and bases[0].project_id is None
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_project_requires_owner(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """project 库仅项目 owner 可建 → 非 owner 403."""
        project = Project(id=PROJECT_ID, name="P", owner_id=OTHER_ID)
        session_override([_full_result([project])])
        resp = await client.post(
            "/api/v1/kb-bases",
            json={"scope": "project", "name": "项目库", "project_id": str(PROJECT_ID)},
            headers=headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_project_without_project_id(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """project 库必须指定 project_id → 400."""
        session_override([])
        resp = await client.post(
            "/api/v1/kb-bases", json={"scope": "project", "name": "项目库"}, headers=headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_company_requires_admin(
        self, client: AsyncClient, session_override, headers, monkeypatch
    ) -> None:
        """company 库仅管理员可建 → 非管理员 403."""
        session_override([_full_result([_user(USER_ID, "u@x.com")])])

        async def deny(db, user, code):
            return False

        monkeypatch.setattr("app.core.rbac.has_permission", deny)
        resp = await client.post(
            "/api/v1/kb-bases", json={"scope": "company", "name": "公司库"}, headers=headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_company_by_admin(
        self, client: AsyncClient, session_override, monkeypatch
    ) -> None:
        """管理员建 company 库：project_id/owner_id 均置空."""
        session = session_override(
            [_full_result([_user(USER_ID, "u@x.com", "kb_admin")]), _full_result([])]
        )

        async def allow(db, user, code):
            return code == "kb:manage"

        monkeypatch.setattr("app.core.rbac.has_permission", allow)

        async def fake_refresh(obj):
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = obj.created_at or datetime.now(UTC)

        session.refresh.side_effect = fake_refresh
        token = create_access_token(str(USER_ID))
        resp = await client.post(
            "/api/v1/kb-bases",
            json={"scope": "company", "name": "行业案例库", "project_id": str(PROJECT_ID)},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["scope"] == "company"
        assert data["project_id"] is None
        assert data["owner_id"] is None

    @pytest.mark.asyncio
    async def test_create_invalid_scope(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """非法 scope → 400."""
        session_override([])
        resp = await client.post(
            "/api/v1/kb-bases", json={"scope": "team", "name": "x"}, headers=headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_duplicate_name_in_scope(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """同域重名 → 400."""
        dup = _base("personal", "我的库", owner_id=USER_ID)
        session_override([_full_result([dup])])
        resp = await client.post(
            "/api/v1/kb-bases", json={"scope": "personal", "name": "我的库"}, headers=headers
        )
        assert resp.status_code == 400


class TestUpdateDeleteKbBase:
    """PATCH / DELETE /kb-bases/{id} 写权限."""

    @pytest.mark.asyncio
    async def test_patch_by_owner(self, client: AsyncClient, session_override, headers) -> None:
        """个人库 owner 编辑名称/描述成功."""
        base = _base("personal", "旧名", owner_id=USER_ID)
        session_override([_full_result([base])])
        resp = await client.patch(
            f"/api/v1/kb-bases/{base.id}",
            json={"name": "新名", "description": "说明"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "新名"
        assert base.name == "新名"

    @pytest.mark.asyncio
    async def test_patch_by_non_owner_forbidden(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """非 owner 编辑他人个人库 → 403."""
        base = _base("personal", "他人库", owner_id=OTHER_ID)
        session_override([_full_result([base])])
        resp = await client.patch(
            f"/api/v1/kb-bases/{base.id}", json={"name": "x"}, headers=headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client: AsyncClient, session_override, headers) -> None:
        session_override([_full_result([])])
        resp = await client.delete(f"/api/v1/kb-bases/{uuid.uuid4()}", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_cascades_materials(
        self, client: AsyncClient, session_override, headers, monkeypatch
    ) -> None:
        """删库：库内素材一并删除（MinIO + 记录）+ 审计 + commit."""
        base = _base("personal", "我的库", owner_id=USER_ID)
        doc = Document(
            project_id=None,
            doc_type="kb_material",
            title="a.pdf",
            storage_key=f"global/{uuid.uuid4()}/a.pdf",
            status="indexed",
            kb_id=base.id,
        )
        session = session_override([_full_result([base]), _full_result([doc])])
        monkeypatch.setattr("app.api.kb_bases.storage_service.delete_file", lambda *a, **k: None)
        resp = await client.delete(f"/api/v1/kb-bases/{base.id}", headers=headers)
        assert resp.status_code == 200
        # 素材 + 库两条 delete
        assert session.delete.await_count == 2
        session.commit.assert_awaited()


class TestKbBaseMaterials:
    """GET /kb-bases/{id}/materials."""

    @pytest.mark.asyncio
    async def test_others_personal_base_404(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """不可见库（他人个人库）→ 404 而非空列表（防枚举探测）."""
        base = _base("personal", "他人库", owner_id=OTHER_ID)
        session_override([_full_result([base])])
        resp = await client.get(f"/api/v1/kb-bases/{base.id}/materials", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_company_base_materials_paginated(
        self, client: AsyncClient, session_override, headers
    ) -> None:
        """公司库全员可读，返回库内素材分页列表."""
        base = _base("company", "公司公共库")
        doc = Document(
            project_id=None,
            doc_type="kb_material",
            title="手册.pdf",
            storage_key="global/x/手册.pdf",
            status="indexed",
            kb_id=base.id,
        )
        doc.id = uuid.uuid4()
        doc.created_at = datetime.now(UTC)
        count = MagicMock()
        count.scalar.return_value = 1
        items = MagicMock()
        items.all.return_value = [(doc, "张三")]
        session_override([_full_result([base]), count, items])
        resp = await client.get(f"/api/v1/kb-bases/{base.id}/materials", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["title"] == "手册.pdf"
        assert data["items"][0]["uploader_name"] == "张三"
