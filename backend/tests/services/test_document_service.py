"""document_service 单元测试 — 批次 1c：documents API 直连 DB 逻辑下沉.

覆盖：文档登记/归属校验/列表分页/重新解析重置/格式要求覆盖/
评分点与技术需求读写/废标条款删旧插新。
DB 会话以 AsyncMock + execute 序列模拟（与 API 测试同模式）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.models.document import DisqualificationClause, Document
from app.services.document import document_service

PROJECT_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _session(seq: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = seq
    session.add = MagicMock()
    return session


def _doc(doc_type: str = "tender_file", status: str = "parsed") -> Document:
    return Document(
        id=DOC_ID,
        project_id=PROJECT_ID,
        doc_type=doc_type,
        title="招标文件.docx",
        storage_key="k",
        status=status,
        created_at=datetime.now(UTC),
    )


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_returns_doc_in_project(self) -> None:
        doc = _doc()
        got = await document_service.get_document(_session([_result(doc)]), PROJECT_ID, DOC_ID)
        assert got is doc

    @pytest.mark.asyncio
    async def test_missing_doc_4004(self) -> None:
        with pytest.raises(BizError) as exc:
            await document_service.get_document(_session([_result(None)]), PROJECT_ID, DOC_ID)
        assert exc.value.code == 4004

    @pytest.mark.asyncio
    async def test_cross_project_doc_4004(self) -> None:
        """文档不属本项目 → 4004（防越权）."""
        foreign = Document(
            id=DOC_ID,
            project_id=uuid.uuid4(),
            doc_type="tender_file",
            title="x.pdf",
            storage_key="foreign/x.pdf",
        )
        with pytest.raises(BizError) as exc:
            await document_service.get_document(_session([_result(foreign)]), PROJECT_ID, DOC_ID)
        assert exc.value.code == 4004


class TestLoadTenderDocForFormat:
    @pytest.mark.asyncio
    async def test_non_tender_doc_4010(self) -> None:
        doc = _doc(doc_type="kb_material")
        with pytest.raises(BizError) as exc:
            await document_service.load_tender_doc_for_format(
                _session([_result(doc)]), PROJECT_ID, DOC_ID
            )
        assert exc.value.code == 4010
        assert exc.value.message == "仅招标文件支持格式要求"


class TestRegisterDocument:
    @pytest.mark.asyncio
    async def test_adds_flushes_and_refreshes(self) -> None:
        session = _session([])
        doc = await document_service.register_document(
            session, PROJECT_ID, "tender_file", "tender.pdf", "storage/key", USER_ID
        )
        assert doc.status == "uploaded"
        assert doc.doc_type == "tender_file"
        assert doc.created_by == USER_ID
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()
        session.commit.assert_not_awaited()


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_returns_items_and_total(self) -> None:
        docs = [_doc()]
        session = _session([_scalar_result(1), _scalars_result(docs)])
        items, total = await document_service.list_documents(
            session, PROJECT_ID, doc_type="tender_file", page=2, page_size=5
        )
        assert items == docs
        assert total == 1

    @pytest.mark.asyncio
    async def test_total_defaults_to_zero(self) -> None:
        session = _session([_scalar_result(None), _scalars_result([])])
        items, total = await document_service.list_documents(session, PROJECT_ID)
        assert items == []
        assert total == 0


class TestPrepareReparse:
    @pytest.mark.asyncio
    async def test_clears_results_and_resets_status(self) -> None:
        """清旧评分点 + sp_derived 衍生需求 → 状态重置 uploaded（仅 flush 不 commit）."""
        doc = _doc(status="parsed")
        session = _session([_result(doc), _result(None), _result(None)])
        got = await document_service.prepare_reparse(session, PROJECT_ID, DOC_ID)
        assert got.status == "uploaded"
        deletes = [
            c
            for c in session.execute.call_args_list[1:]
            if str(c.args[0]).lstrip().upper().startswith("DELETE")
        ]
        assert len(deletes) == 2
        delete_params = [str(c.args[0].compile().params) for c in deletes]
        assert any("sp_derived" in p for p in delete_params)
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_non_tender_doc(self) -> None:
        doc = _doc(doc_type="kb_material")
        with pytest.raises(BizError) as exc:
            await document_service.prepare_reparse(_session([_result(doc)]), PROJECT_ID, DOC_ID)
        assert exc.value.code == 4010
        assert exc.value.message == "仅招标文件支持重新解析"

    @pytest.mark.asyncio
    async def test_rejects_parsing_doc(self) -> None:
        doc = _doc(status="parsing")
        with pytest.raises(BizError) as exc:
            await document_service.prepare_reparse(_session([_result(doc)]), PROJECT_ID, DOC_ID)
        assert exc.value.code == 4010
        assert exc.value.message == "文档正在解析中，请稍后重试"

    @pytest.mark.asyncio
    async def test_rejects_uploaded_doc(self) -> None:
        doc = _doc(status="uploaded")
        with pytest.raises(BizError) as exc:
            await document_service.prepare_reparse(_session([_result(doc)]), PROJECT_ID, DOC_ID)
        assert exc.value.code == 4010
        assert exc.value.message == "解析任务已排队，请等待完成"


class TestSaveFormatRequirements:
    @pytest.mark.asyncio
    async def test_overwrites_meta_and_flushes(self) -> None:
        """整体替换新 dict 确保 JSON 列标记脏（原地改 key 不触发变更检测）."""
        doc = _doc()
        doc.meta = {"format_requirements": [{"category": "other", "requirement": "旧"}]}
        items = [{"category": "font_body", "requirement": "正文宋体小四"}]
        session = _session([_result(doc)])
        got = await document_service.save_format_requirements(session, PROJECT_ID, DOC_ID, items)
        assert got.meta["format_requirements"] == items
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()


class TestScorePoints:
    @pytest.mark.asyncio
    async def test_list_returns_rows(self) -> None:
        session = _session([_scalars_result(["sp1", "sp2"])])
        items = await document_service.list_score_points(session, PROJECT_ID)
        assert items == ["sp1", "sp2"]

    @pytest.mark.asyncio
    async def test_update_applies_fields(self) -> None:
        from app.models.document import ScorePoint

        sp = ScorePoint(
            id=uuid.uuid4(),
            project_id=PROJECT_ID,
            doc_id=uuid.uuid4(),
            clause_no="1",
            item="x",
            is_star=False,
        )
        session = _session([_result(sp)])
        got = await document_service.update_score_point(session, PROJECT_ID, sp.id, "策略", True)
        assert got.strategy == "策略"
        assert got.confirmed is True
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_missing_4004(self) -> None:
        with pytest.raises(BizError) as exc:
            await document_service.update_score_point(
                _session([_result(None)]), PROJECT_ID, uuid.uuid4(), None, None
            )
        assert exc.value.code == 4004


class TestTechRequirements:
    @pytest.mark.asyncio
    async def test_list_returns_rows(self) -> None:
        session = _session([_scalars_result(["tr1"])])
        items = await document_service.list_tech_requirements(session, PROJECT_ID)
        assert items == ["tr1"]


class TestDisqualificationClauses:
    @pytest.mark.asyncio
    async def test_list_doc_clauses_returns_rows(self) -> None:
        clause = DisqualificationClause(
            id=uuid.uuid4(),
            project_id=PROJECT_ID,
            doc_id=DOC_ID,
            clause_no="2.1",
            title="资质要求",
        )
        session = _session([_scalars_result([clause])])
        items = await document_service.list_doc_clauses(session, PROJECT_ID, DOC_ID)
        assert items == [clause]

    @pytest.mark.asyncio
    async def test_replace_deletes_old_and_inserts_new(self) -> None:
        session = _session([_result(None)])
        cleaned = [{"clause_no": "2.1", "title": "资质要求"}]
        await document_service.replace_doc_clauses(session, PROJECT_ID, DOC_ID, cleaned)
        stmt = str(session.execute.call_args_list[0].args[0]).lstrip().upper()
        assert stmt.startswith("DELETE")
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        session.commit.assert_not_awaited()
