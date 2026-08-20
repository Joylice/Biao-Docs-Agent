"""全局资料库 API 测试 — /kb/materials 上传/列表/删除/检索（二期）.

覆盖：
- upload：成功路径（project_id IS NULL 登记 + 审计 + 入队）、类型/大小校验、401
- list：分页契约、仅全局资料可见、401
- delete：成功 + 审计、404、项目级文档不可经全局接口删除（隔离）、401
- delete 权限（二期决策：删除限管理员 get_current_admin_id）：
  未配置管理员拒绝、非管理员 403、管理员放行
- search：命中返回 items/total、委托 rag_service、空 q 422、401
"""

import io
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
from app.models.user import User

USER_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
KB_ADMIN_ID = uuid.uuid4()  # 三期：资料库管理员角色
DOC_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _global_doc() -> Document:
    return Document(
        id=DOC_ID,
        project_id=None,
        doc_type="kb_material",
        title="产品手册.pdf",
        storage_key=f"global/{DOC_ID}/产品手册.pdf",
        status="indexed",
        created_at=datetime.now(UTC),
    )


def _user(user_id: uuid.UUID, email: str, role: str = "member") -> User:
    return User(id=user_id, email=email, password_hash="x", display_name="测试用户", role=role)


@pytest.fixture
def override_db() -> Generator:
    """按预设 scalar 序列覆盖 get_db，用例结束清理."""

    def _override(scalar_sequence: list) -> AsyncMock:
        session = AsyncMock()
        session.execute.side_effect = [_result(s) for s in scalar_sequence]
        app.dependency_overrides[get_db] = lambda: session
        return session

    yield _override
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def headers() -> dict[str, str]:
    token = create_access_token(str(USER_ID))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    token = create_access_token(str(ADMIN_ID))
    return {"Authorization": f"Bearer {token}"}


class TestUploadMaterial:
    """POST /kb/materials."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/kb/materials")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_registers_global_doc(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """上传成功：登记 project_id IS NULL 的全局文档 + 审计 + 向量化入队."""
        session = override_db([])
        captured: dict = {}

        monkeypatch.setattr(
            "app.api.kb.storage_service.upload_file",
            lambda *a, **k: f"global/{DOC_ID}/手册.pdf",
        )

        async def fake_enqueue(project_id, doc_id):
            captured["enqueue"] = (project_id, doc_id)
            return True

        monkeypatch.setattr("app.api.kb.task_service.enqueue_index_document", fake_enqueue)

        async def fake_refresh(obj):
            obj.id = DOC_ID
            obj.created_at = datetime.now(UTC)

        session.refresh.side_effect = fake_refresh

        files = {"file": ("手册.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        token = create_access_token(str(USER_ID))
        resp = await client.post(
            "/api/v1/kb/materials", files=files, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

        # 登记 + 审计两条 add；文档必须为全局（project_id IS NULL）
        added = [c.args[0] for c in session.add.call_args_list]
        docs = [a for a in added if isinstance(a, Document)]
        assert len(docs) == 1
        assert docs[0].project_id is None
        assert docs[0].doc_type == "kb_material"
        session.commit.assert_awaited()
        # 入队以 project_id=None 调用
        assert captured["enqueue"][0] is None

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_content_type(
        self, client: AsyncClient, override_db, headers
    ) -> None:
        """不支持的文件类型 → 400（ValidationError，未到存储/入队环节）."""
        override_db([])
        files = {"file": ("evil.exe", io.BytesIO(b"MZ"), "application/x-msdownload")}
        resp = await client.post("/api/v1/kb/materials", files=files, headers=headers)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_with_category_and_tags(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """三期 S2：上传携带 category/tags（逗号分隔字符串）落库."""
        session = override_db([])
        monkeypatch.setattr(
            "app.api.kb.storage_service.upload_file", lambda *a, **k: "global/x/证书.pdf"
        )

        async def fake_enqueue(project_id, doc_id):
            return True

        monkeypatch.setattr("app.api.kb.task_service.enqueue_index_document", fake_enqueue)

        async def fake_refresh(obj):
            obj.id = DOC_ID
            obj.created_at = datetime.now(UTC)

        session.refresh.side_effect = fake_refresh

        files = {"file": ("证书.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await client.post(
            "/api/v1/kb/materials",
            files=files,
            data={"category": "qualification", "tags": "ISO27001, 安全"},
            headers=headers,
        )
        assert resp.status_code == 200
        added_docs = [
            a for c in session.add.call_args_list if isinstance((a := c.args[0]), Document)
        ]
        assert added_docs[0].category == "qualification"
        assert added_docs[0].tags == ["ISO27001", "安全"]

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_category(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """非法分类 → 400（枚举校验）."""
        override_db([])
        monkeypatch.setattr(
            "app.api.kb.storage_service.upload_file", lambda *a, **k: "global/x/a.pdf"
        )
        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await client.post(
            "/api/v1/kb/materials",
            files=files,
            data={"category": "not_a_category"},
            headers=headers,
        )
        assert resp.status_code == 400


class TestUploadMaterialKbAttribution:
    """POST /kb/materials 知识库归属（kb_id，阶段 1）."""

    def _personal_base(self) -> KnowledgeBase:
        base = KnowledgeBase(
            project_id=None, owner_id=USER_ID, scope="personal", name="我的库"
        )
        base.id = uuid.uuid4()
        return base

    @pytest.mark.asyncio
    async def test_upload_into_own_personal_base(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """上传携带 kb_id 归入本人个人库（doc.kb_id 落库）."""
        base = self._personal_base()
        session = override_db([base])
        monkeypatch.setattr(
            "app.api.kb.storage_service.upload_file", lambda *a, **k: "global/x/a.pdf"
        )

        async def fake_enqueue(project_id, doc_id):
            return True

        monkeypatch.setattr("app.api.kb.task_service.enqueue_index_document", fake_enqueue)

        async def fake_refresh(obj):
            obj.id = obj.id or DOC_ID
            obj.created_at = datetime.now(UTC)

        session.refresh.side_effect = fake_refresh

        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await client.post(
            "/api/v1/kb/materials",
            files=files,
            data={"kb_id": str(base.id)},
            headers=headers,
        )
        assert resp.status_code == 200
        added_docs = [
            a for c in session.add.call_args_list if isinstance((a := c.args[0]), Document)
        ]
        assert added_docs[0].kb_id == base.id

    @pytest.mark.asyncio
    async def test_upload_into_unknown_base_returns_4004(
        self, client: AsyncClient, override_db, headers
    ) -> None:
        """kb_id 对应库不存在 → 4004（HTTP 404）."""
        override_db([None])
        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await client.post(
            "/api/v1/kb/materials",
            files=files,
            data={"kb_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_upload_into_others_base_forbidden(
        self, client: AsyncClient, override_db, headers
    ) -> None:
        """归入他人个人库 → 403（库写权限按 scope 判定）."""
        base = KnowledgeBase(
            project_id=None, owner_id=uuid.uuid4(), scope="personal", name="他人库"
        )
        base.id = uuid.uuid4()
        override_db([base])
        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await client.post(
            "/api/v1/kb/materials",
            files=files,
            data={"kb_id": str(base.id)},
            headers=headers,
        )
        assert resp.status_code == 403


class TestListMaterials:
    """GET /kb/materials."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/kb/materials")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_returns_paginated_global_docs(self, client: AsyncClient, headers) -> None:
        """列表契约：code=0 + items/total，SQL 限定 project_id IS NULL，返回 uploader_name."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        # 三期 S2：LEFT JOIN users 返回 (Document, uploader_name) 元组
        items_result.all.return_value = [(_global_doc(), "张三")]
        session.execute.side_effect = [count_result, items_result]
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get(
                "/api/v1/kb/materials", params={"page": 1, "page_size": 10}, headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 1
            assert data["items"][0]["title"] == "产品手册.pdf"
            assert data["items"][0]["uploader_name"] == "张三"
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_list_uploader_name_empty_when_no_creator(
        self, client: AsyncClient, headers
    ) -> None:
        """created_by 为空（LEFT JOIN 未命中）→ uploader_name 空串."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        items_result.all.return_value = [(_global_doc(), None)]
        session.execute.side_effect = [count_result, items_result]
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get("/api/v1/kb/materials", headers=headers)
            assert resp.json()["data"]["items"][0]["uploader_name"] == ""
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_list_category_tag_filters_pushed_to_sql(
        self, client: AsyncClient, headers
    ) -> None:
        """category/tag 过滤条件下推 SQL（tag 用 JSON 包含匹配）."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        items_result = MagicMock()
        items_result.all.return_value = []
        session.execute.side_effect = [count_result, items_result]
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get(
                "/api/v1/kb/materials",
                params={"category": "qualification", "tag": "ISO27001"},
                headers=headers,
            )
            assert resp.status_code == 200
            stmts = " ".join(str(c.args[0]) for c in session.execute.call_args_list).replace(
                "\n", " "
            )
            assert "category" in stmts
            assert "@>" in stmts  # tag 过滤用 JSON 包含操作符（值为 bind 参数）
        finally:
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_list_kb_id_filter_and_visibility_join(
        self, client: AsyncClient, headers
    ) -> None:
        """kb_id 过滤 + 可见性 outerjoin（knowledge_bases + project_members）下推 SQL."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        items_result = MagicMock()
        items_result.all.return_value = []
        session.execute.side_effect = [count_result, items_result]
        app.dependency_overrides[get_db] = lambda: session
        try:
            resp = await client.get(
                "/api/v1/kb/materials",
                params={"kb_id": str(uuid.uuid4())},
                headers=headers,
            )
            assert resp.status_code == 200
            stmts = " ".join(str(c.args[0]) for c in session.execute.call_args_list).replace(
                "\n", " "
            )
            assert "knowledge_bases.id" in stmts  # 可见性 LEFT JOIN
            assert "project_members" in stmts  # 项目库成员判定 JOIN
            assert "documents.kb_id" in stmts  # kb_id 过滤条件
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestDeleteMaterial:
    """DELETE /kb/materials/{doc_id}（二期：删除限管理员）."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_4004(
        self, client: AsyncClient, override_db, admin_headers, monkeypatch
    ) -> None:
        """不存在的资料 → BizError 4004（HTTP 404）."""
        override_db([_user(ADMIN_ID, "admin@bidagent.com"), None])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "admin@bidagent.com")
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=admin_headers)
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_delete_rejects_project_level_doc(
        self, client: AsyncClient, override_db, admin_headers, monkeypatch
    ) -> None:
        """项目级文档不可经全局接口删除（隔离：查询限定 project_id IS NULL）."""
        session = override_db([_user(ADMIN_ID, "admin@bidagent.com"), None])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "admin@bidagent.com")
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=admin_headers)
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004
        # 隔离断言：查询语句必须带 project_id IS NULL 过滤（防止回归去掉隔离条件）
        doc_stmt = str(session.execute.call_args_list[1].args[0])
        assert "project_id IS NULL" in doc_stmt.replace("\n", " ")

    @pytest.mark.asyncio
    async def test_delete_by_admin_succeeds(
        self, client: AsyncClient, override_db, admin_headers, monkeypatch
    ) -> None:
        """管理员删除全局资料：记录删除 + 审计 + commit."""
        session = override_db([_user(ADMIN_ID, "admin@bidagent.com"), _global_doc()])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "admin@bidagent.com")
        monkeypatch.setattr("app.api.kb.storage_service.delete_file", lambda *a, **k: None)

        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == str(DOC_ID)
        session.delete.assert_awaited()
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_by_non_admin_forbidden(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """非管理员删除 → 403（二期权限收口）."""
        override_db([_user(USER_ID, "user@bidagent.com")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "admin@bidagent.com")
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_without_admin_config_forbidden(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """未配置 BID_ADMIN_USER_IDS 且 role 非管理角色 → 403（不放宽为任意登录用户）."""
        override_db([_user(USER_ID, "user@bidagent.com")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.delete(f"/api/v1/kb/materials/{DOC_ID}", headers=headers)
        assert resp.status_code == 403


class TestSearchMaterials:
    """GET /kb/materials/search."""

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/kb/materials/search", params={"q": "高可用"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, client: AsyncClient, headers) -> None:
        resp = await client.get("/api/v1/kb/materials/search", params={"q": ""}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_returns_hits_with_doc_scope(
        self, client: AsyncClient, headers, monkeypatch
    ) -> None:
        """检索命中：以全局资料 doc_ids 限定范围委托 rag_service."""
        session = AsyncMock()
        doc_result = MagicMock()
        doc_result.all.return_value = [(DOC_ID,)]
        session.execute.return_value = doc_result
        app.dependency_overrides[get_db] = lambda: session

        captured: dict = {}

        async def fake_search_materials(
            db, project_id, query, top_k=5, min_score=0.0, doc_ids=None
        ):
            captured["query"] = query
            captured["top_k"] = top_k
            captured["doc_ids"] = doc_ids
            return [
                {
                    "chunk_id": str(uuid.uuid4()),
                    "doc_id": str(DOC_ID),
                    "title": "产品手册.pdf",
                    "content": "支持高可用部署",
                    "page_no": 1,
                    "score": 0.9,
                }
            ]

        monkeypatch.setattr("app.api.kb.rag_service.search_materials", fake_search_materials)
        try:
            resp = await client.get(
                "/api/v1/kb/materials/search",
                params={"q": "高可用", "top_k": 3},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 1
            assert data["items"][0]["title"] == "产品手册.pdf"
            assert captured["doc_ids"] == [DOC_ID]
            assert captured["top_k"] == 3
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestPatchMaterial:
    """PATCH /kb/materials/{doc_id}（三期 S2：编辑限资料库管理员）."""

    def _kb_admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(str(KB_ADMIN_ID))}"}

    @pytest.mark.asyncio
    async def test_no_auth(self, client: AsyncClient) -> None:
        resp = await client.patch(f"/api/v1/kb/materials/{DOC_ID}", json={"title": "x"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_member_forbidden(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """member 角色编辑 → 403."""
        override_db([_user(USER_ID, "user@bidagent.com")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.patch(
            f"/api/v1/kb/materials/{DOC_ID}", json={"title": "x"}, headers=headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_succeeds_with_audit(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """kb_admin 编辑：title/category/tags 更新 + 审计 kb.material_update + commit."""
        doc = _global_doc()
        session = override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin"), doc])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")

        resp = await client.patch(
            f"/api/v1/kb/materials/{DOC_ID}",
            json={"title": "新名称.pdf", "category": "other", "tags": ["安全", "ISO27001"]},
            headers=self._kb_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "新名称.pdf"
        assert doc.title == "新名称.pdf"
        assert doc.category == "other"
        assert doc.tags == ["安全", "ISO27001"]
        session.commit.assert_awaited()
        # 审计落库（与文档同事务 add）
        from app.models.audit_log import AuditLog

        audits = [a for c in session.add.call_args_list if isinstance((a := c.args[0]), AuditLog)]
        assert audits and audits[0].action == "kb.material_update"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_4004(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """资料不存在 → BizError 4004（HTTP 404）."""
        override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin"), None])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.patch(
            f"/api/v1/kb/materials/{DOC_ID}",
            json={"title": "x"},
            headers=self._kb_admin_headers(),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_update_rejects_bad_category(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """非法分类 → 422（Pydantic 枚举校验）."""
        override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.patch(
            f"/api/v1/kb/materials/{DOC_ID}",
            json={"category": "bad_category"},
            headers=self._kb_admin_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_rejects_too_many_tags(
        self, client: AsyncClient, override_db, monkeypatch
    ) -> None:
        """标签超上限 → 422."""
        override_db([_user(KB_ADMIN_ID, "kb@x.com", "kb_admin")])
        monkeypatch.setattr("app.core.deps.settings.admin_user_ids", "")
        resp = await client.patch(
            f"/api/v1/kb/materials/{DOC_ID}",
            json={"tags": [f"t{i}" for i in range(11)]},
            headers=self._kb_admin_headers(),
        )
        assert resp.status_code == 422


class TestMaterialDownload:
    """素材下载代理（阶段 2：MinIO 浏览器可达性修复）."""

    @pytest.mark.asyncio
    async def test_download_no_auth(self, client: AsyncClient) -> None:
        """未认证下载 → 401."""
        resp = await client.get(f"/api/v1/kb/materials/{DOC_ID}/download")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_download_success(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """登录用户下载全局素材 → 200 字节 + Content-Disposition."""
        override_db([_global_doc()])
        monkeypatch.setattr(
            "app.services.storage_service.download_file", lambda key: b"KB-BYTES"
        )
        resp = await client.get(f"/api/v1/kb/materials/{DOC_ID}/download", headers=headers)
        assert resp.status_code == 200
        assert resp.content == b"KB-BYTES"
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "filename*=" in resp.headers.get("content-disposition", "")

    @pytest.mark.asyncio
    async def test_download_rejects_project_doc(
        self, client: AsyncClient, override_db, headers, monkeypatch
    ) -> None:
        """项目级文档不可经全局接口下载（隔离）→ 4004."""
        doc = _global_doc()
        doc.project_id = uuid.uuid4()
        override_db([doc])
        monkeypatch.setattr(
            "app.services.storage_service.download_file", lambda key: b"X"
        )
        resp = await client.get(f"/api/v1/kb/materials/{DOC_ID}/download", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004

    @pytest.mark.asyncio
    async def test_download_missing_returns_4004(
        self, client: AsyncClient, override_db, headers
    ) -> None:
        """素材不存在 → 4004."""
        override_db([None])
        resp = await client.get(f"/api/v1/kb/materials/{DOC_ID}/download", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["code"] == 4004
