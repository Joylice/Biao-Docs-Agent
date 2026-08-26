"""知识库服务测试 — 挂载合并语义与可见性条件（阶段 1）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.project import ProjectMember
from app.services.infra import kb_base_service


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestResolveMountDocIds:
    """库级 ∪ 文档级挂载合并为检索 doc_ids."""

    @pytest.mark.asyncio
    async def test_both_none_returns_none(self) -> None:
        """两者均 None = 项目全量检索（不查库）."""
        session = AsyncMock()
        result = await kb_base_service.resolve_mount_doc_ids(session, None, None)
        assert result is None
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_kb_ids_resolved_to_material_docs(self) -> None:
        """库级挂载 → 展开为库内素材 doc_id 列表."""
        kb_id = uuid.uuid4()
        doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
        session = AsyncMock()
        session.execute.return_value = _rows_result([(doc_b,), (doc_a,)])
        result = await kb_base_service.resolve_mount_doc_ids(session, [str(kb_id)], None)
        assert result == sorted([doc_a, doc_b], key=str)

    @pytest.mark.asyncio
    async def test_union_dedup_and_empty_means_no_mount(self) -> None:
        """库级与文档级并集去重；均为空列表 = 明确不挂载（返回空列表非 None）."""
        kb_id = uuid.uuid4()
        doc_shared, doc_only = uuid.uuid4(), uuid.uuid4()
        session = AsyncMock()
        session.execute.return_value = _rows_result([(doc_shared,)])
        result = await kb_base_service.resolve_mount_doc_ids(
            session, [str(kb_id)], [str(doc_shared), str(doc_only)]
        )
        assert result == sorted([doc_shared, doc_only], key=str)

    @pytest.mark.asyncio
    async def test_empty_lists_mean_explicit_no_mount(self) -> None:
        session = AsyncMock()
        result = await kb_base_service.resolve_mount_doc_ids(session, [], [])
        assert result == []


class TestResolveDocIds:
    """知识库 → 库内素材 doc_id 列表."""

    @pytest.mark.asyncio
    async def test_empty_base_ids_short_circuit(self) -> None:
        session = AsyncMock()
        assert await kb_base_service.resolve_doc_ids(session, []) == []
        session.execute.assert_not_awaited()


class TestMaterialVisibilityClause:
    """素材可见性 SQL 条件构成."""

    def test_clause_covers_null_company_personal_project(self) -> None:
        clause = kb_base_service.material_visibility_clause(uuid.uuid4(), ProjectMember.user_id)
        text = str(clause.compile(compile_kwargs={"literal_binds": False}))
        assert "knowledge_bases.scope" in text
        assert "documents.kb_id IS NULL" in text.replace("\n", " ")
        assert "project_members.user_id IS NOT NULL" in text.replace("\n", " ")
