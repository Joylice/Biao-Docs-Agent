"""kb_material_service 单元测试 — 全局素材 DB 操作（批次 1b 自 api/kb.py 等下沉）.

覆盖行为等价：
- 登记：project_id IS NULL / doc_type=kb_material / status=uploaded，只 flush 不 commit
- 取回：全局资料查询限定 project_id IS NULL（隔离），不存在 → 4004
- 下载：项目级文档/非 kb_material 拒绝（4004）
- 编辑：title 去空白校验（空 → 4000），changed 字段清单
- 检索范围 doc_ids / 库内素材查询 / 全局列表（count+items 顺序与可见性 JOIN）
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError, ValidationError
from app.models.document import Document
from app.services import kb_material_service

DOC_ID = uuid.uuid4()
KB_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


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


def _scalar_session(scalar: object) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    session.execute.return_value = result
    return session


class TestRegisterMaterial:
    async def test_registers_global_doc_flush_no_commit(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        doc = await kb_material_service.register_material(
            session,
            title="手册.pdf",
            storage_key="global/x/手册.pdf",
            category="qualification",
            tags=["ISO27001"],
            kb_id=KB_ID,
            user_id=USER_ID,
        )
        assert doc.project_id is None
        assert doc.doc_type == "kb_material"
        assert doc.status == "uploaded"
        assert doc.title == "手册.pdf"
        assert doc.storage_key == "global/x/手册.pdf"
        assert doc.category == "qualification"
        assert doc.tags == ["ISO27001"]
        assert doc.kb_id == KB_ID
        assert doc.created_by == USER_ID
        session.add.assert_called_once_with(doc)
        session.flush.assert_awaited()
        session.refresh.assert_awaited()
        session.commit.assert_not_awaited()


class TestGetGlobalMaterial:
    async def test_missing_raises_4004(self) -> None:
        session = _scalar_session(None)
        with pytest.raises(BizError) as exc:
            await kb_material_service.get_global_material(session, DOC_ID)
        assert exc.value.code == 4004
        assert exc.value.message == "资料不存在"

    async def test_query_scoped_to_project_id_null(self) -> None:
        """隔离回归：查询语句必须带 project_id IS NULL 过滤."""
        session = _scalar_session(None)
        with pytest.raises(BizError):
            await kb_material_service.get_global_material(session, DOC_ID)
        stmt = str(session.execute.call_args.args[0]).replace("\n", " ")
        assert "project_id IS NULL" in stmt

    async def test_returns_doc(self) -> None:
        doc = _global_doc()
        session = _scalar_session(doc)
        result = await kb_material_service.get_global_material(session, DOC_ID)
        assert result is doc


class TestGetMaterialForDownload:
    async def test_missing_raises_4004(self) -> None:
        session = _scalar_session(None)
        with pytest.raises(BizError) as exc:
            await kb_material_service.get_material_for_download(session, DOC_ID)
        assert exc.value.code == 4004

    async def test_rejects_project_doc(self) -> None:
        doc = _global_doc()
        doc.project_id = uuid.uuid4()
        session = _scalar_session(doc)
        with pytest.raises(BizError) as exc:
            await kb_material_service.get_material_for_download(session, DOC_ID)
        assert exc.value.code == 4004

    async def test_rejects_non_kb_material(self) -> None:
        doc = _global_doc()
        doc.doc_type = "bid_document"
        session = _scalar_session(doc)
        with pytest.raises(BizError) as exc:
            await kb_material_service.get_material_for_download(session, DOC_ID)
        assert exc.value.code == 4004

    async def test_returns_global_material(self) -> None:
        doc = _global_doc()
        session = _scalar_session(doc)
        result = await kb_material_service.get_material_for_download(session, DOC_ID)
        assert result is doc


class TestUpdateMaterial:
    async def test_missing_raises_4004(self) -> None:
        session = _scalar_session(None)
        with pytest.raises(BizError) as exc:
            await kb_material_service.update_material(
                session, DOC_ID, title="x.pdf", category=None, tags=None
            )
        assert exc.value.code == 4004

    async def test_blank_title_raises_validation(self) -> None:
        session = _scalar_session(_global_doc())
        with pytest.raises(ValidationError) as exc:
            await kb_material_service.update_material(
                session, DOC_ID, title="   ", category=None, tags=None
            )
        assert exc.value.message == "标题不能为空"

    async def test_applies_changes_and_reports_changed(self) -> None:
        doc = _global_doc()
        session = _scalar_session(doc)
        updated, changed = await kb_material_service.update_material(
            session, DOC_ID, title="新名称.pdf", category="other", tags=["安全", "ISO27001"]
        )
        assert updated is doc
        assert doc.title == "新名称.pdf"
        assert doc.category == "other"
        assert doc.tags == ["安全", "ISO27001"]
        assert changed == ["title", "category", "tags"]

    async def test_unchanged_fields_not_reported(self) -> None:
        doc = _global_doc()
        session = _scalar_session(doc)
        _, changed = await kb_material_service.update_material(
            session, DOC_ID, title=None, category="other", tags=None
        )
        assert changed == ["category"]


class TestDeleteMaterial:
    async def test_deletes_doc(self) -> None:
        session = AsyncMock()
        doc = _global_doc()
        await kb_material_service.delete_material(session, doc)
        session.delete.assert_awaited_once_with(doc)
        session.commit.assert_not_awaited()


class TestGlobalMaterialDocIds:
    async def test_returns_ids(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        ids = [uuid.uuid4(), uuid.uuid4()]
        result.all.return_value = [(i,) for i in ids]
        session.execute.return_value = result
        doc_ids = await kb_material_service.global_material_doc_ids(session)
        assert doc_ids == ids
        stmt = str(session.execute.call_args.args[0]).replace("\n", " ")
        assert "project_id IS NULL" in stmt


class TestListGlobalMaterials:
    async def test_count_then_items_with_visibility_join(self) -> None:
        """count 先于 items；可见性 JOIN（knowledge_bases + project_members）下推 SQL."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        items_result.all.return_value = [(_global_doc(), "张三")]
        session.execute.side_effect = [count_result, items_result]

        rows, total = await kb_material_service.list_global_materials(
            session, USER_ID, page=1, page_size=20, category=None, tag=None, kb_id=None
        )
        assert total == 1
        assert len(rows) == 1
        doc, uploader_name = rows[0]
        assert doc.title == "产品手册.pdf"
        assert uploader_name == "张三"
        stmts = " ".join(str(c.args[0]) for c in session.execute.call_args_list).replace("\n", " ")
        assert "knowledge_bases.id" in stmts
        assert "project_members" in stmts
        session.commit.assert_not_awaited()

    async def test_filters_pushed_to_sql(self) -> None:
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        items_result = MagicMock()
        items_result.all.return_value = []
        session.execute.side_effect = [count_result, items_result]

        kb_id = uuid.uuid4()
        await kb_material_service.list_global_materials(
            session,
            USER_ID,
            page=1,
            page_size=20,
            category="qualification",
            tag="ISO27001",
            kb_id=kb_id,
        )
        stmts = " ".join(str(c.args[0]) for c in session.execute.call_args_list).replace("\n", " ")
        assert "category" in stmts
        assert "@>" in stmts
        assert "documents.kb_id" in stmts


class TestListBaseMaterials:
    async def test_returns_docs(self) -> None:
        session = AsyncMock()
        doc = _global_doc()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [doc]
        session.execute.return_value = result
        docs = await kb_material_service.list_base_materials(session, KB_ID)
        assert docs == [doc]

    async def test_paged_count_then_items(self) -> None:
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        items_result.all.return_value = [(_global_doc(), "张三")]
        session.execute.side_effect = [count_result, items_result]
        rows, total = await kb_material_service.list_base_materials_paged(
            session, KB_ID, page=1, page_size=20
        )
        assert total == 1
        assert [r[1] for r in rows] == ["张三"]
