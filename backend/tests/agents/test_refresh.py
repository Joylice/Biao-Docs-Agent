"""refresh_context_node 单元测试 — 对齐方案 B 三层保障.

覆盖：
- 正常路径：从 DB 刷新源数据写回 state，字段齐全，资格需求被过滤，context_version 稳定
- 异常路径：空 project_id / DB 异常 → 返回 {} 保持 state 不变
- reducer 单测：merge_reset_on_empty 空 dict 清空、非空合并、None 处理
"""

import uuid

import pytest

from app.agents import nodes
from app.agents.nodes.refresh import refresh_context_node
from app.agents.state import merge_reset_on_empty
from app.models.document import Document, ScorePoint, TechRequirement
from app.models.project import Project

PROJECT_ID = uuid.uuid4()


class FakeScalarResult:
    """模拟 SQLAlchemy execute 结果."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    """模拟 AsyncSession（按 SQLAlchemy entity 查表返回行）."""

    def __init__(self, rows_by_table: dict | None = None) -> None:
        self.rows_by_table = rows_by_table or {}

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return FakeScalarResult(self.rows_by_table.get(entity, []))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


def _make_db() -> FakeDB:
    """构造含解析结果 + 资格类需求的 DB mock."""
    proj = Project(
        id=PROJECT_ID,
        name="河北项目",
        tender_no="HB-2026-01",
        owner_id=uuid.uuid4(),
        industry="公路机电",
    )
    sp = ScorePoint(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=uuid.uuid4(),
        clause_no="2.2.4(1)",
        item="系统架构",
        score=8,
        criteria="架构合理",
        is_star=False,
        confirmed=True,
    )
    # 纯技术需求（应保留）
    tr_tech = TechRequirement(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=uuid.uuid4(),
        seq=1,
        description="系统需支持高可用部署，响应时间不超过500ms",
        category="架构",
        is_mandatory=True,
    )
    # 资格/商务类需求（应被过滤）
    tr_qual = TechRequirement(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=uuid.uuid4(),
        seq=2,
        description="企业资质：具备公路交通工程专业承包壹级资质，近3年同类业绩",
        category=None,
        is_mandatory=True,
    )
    doc = Document(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_type="tender_file",
        meta={"glossary": [{"term": "TOCC", "canonical": "交通运行协调中心"}]},
    )
    return FakeDB(
        {
            Project: [proj],
            ScorePoint: [sp],
            TechRequirement: [tr_tech, tr_qual],
            Document: [doc],
        }
    )


# ───────────────────────── reducer 单测 ─────────────────────────


class TestMergeResetOnEmpty:
    """merge_reset_on_empty reducer：空 dict/None 表示重置（作废已生成章节）."""

    def test_empty_incoming_resets_to_empty(self):
        """空 dict incoming → 返回 {}（清空）."""
        assert merge_reset_on_empty({"a": "1"}, {}) == {}

    def test_none_incoming_resets_to_empty(self):
        """None incoming → 返回 {}（清空）."""
        assert merge_reset_on_empty({"a": "1"}, None) == {}

    def test_nonempty_merges(self):
        """非空 incoming → 合并（与 operator.or_ 语义一致）."""
        assert merge_reset_on_empty({"a": "1"}, {"b": "2"}) == {"a": "1", "b": "2"}

    def test_nonempty_overwrites_existing_key(self):
        """incoming 含已有 key → 覆盖（与 operator.or_ 语义一致）."""
        assert merge_reset_on_empty({"a": "1"}, {"a": "2"}) == {"a": "2"}

    def test_current_none_with_nonempty_incoming(self):
        """current 为 None + 非空 incoming → 合并为 incoming."""
        assert merge_reset_on_empty(None, {"a": "1"}) == {"a": "1"}

    def test_both_empty(self):
        """current 和 incoming 都为空 → 返回 {}."""
        assert merge_reset_on_empty({}, {}) == {}


# ───────────────────────── refresh_context_node 测试 ─────────────────────────


class TestRefreshContextNode:
    """refresh_context_node：从 DB 刷新源数据写回 state."""

    def _patch_db(self, monkeypatch, db: FakeDB) -> None:
        monkeypatch.setattr(nodes, "async_session_factory", lambda: db)

    @pytest.mark.asyncio
    async def test_refresh_writes_all_fields(self, monkeypatch):
        """正常路径：返回字段齐全（含严格过滤后的评分点/需求/行业/术语表/指纹）."""
        self._patch_db(monkeypatch, _make_db())
        result = await refresh_context_node({"project_id": str(PROJECT_ID)})

        assert "score_points" in result and len(result["score_points"]) == 1
        assert result["score_points"][0]["clause_no"] == "2.2.4(1)"
        assert "tech_requirements" in result
        assert "project_name" in result and result["project_name"] == "河北项目"
        assert "tender_no" in result and result["tender_no"] == "HB-2026-01"
        assert "industry" in result and result["industry"] == "公路机电"
        assert "glossary" in result and result["glossary"][0]["term"] == "TOCC"
        assert "context_version" in result and len(result["context_version"]) == 16

    @pytest.mark.asyncio
    async def test_refresh_filters_qualification_requirements(self, monkeypatch):
        """资格/商务类技术需求被过滤（资质/业绩类），纯技术需求保留."""
        self._patch_db(monkeypatch, _make_db())
        result = await refresh_context_node({"project_id": str(PROJECT_ID)})

        trs = result["tech_requirements"]
        assert len(trs) == 1
        assert "资质" not in trs[0]["description"]
        assert "高可用" in trs[0]["description"]

    @pytest.mark.asyncio
    async def test_context_version_stable_and_changes_with_data(self, monkeypatch):
        """相同数据 → context_version 稳定；数据变更（新增评分点）→ 指纹变化."""
        db = _make_db()
        self._patch_db(monkeypatch, db)
        r1 = await refresh_context_node({"project_id": str(PROJECT_ID)})
        r2 = await refresh_context_node({"project_id": str(PROJECT_ID)})
        assert r1["context_version"] == r2["context_version"]

        # 追加一个已确认评分点 → 指纹应变
        db.rows_by_table[ScorePoint].append(
            ScorePoint(
                id=uuid.uuid4(),
                project_id=PROJECT_ID,
                doc_id=uuid.uuid4(),
                clause_no="2.2.4(2)",
                item="施工方案",
                score=6,
                criteria="施工组织",
                is_star=False,
                confirmed=True,
            )
        )
        r3 = await refresh_context_node({"project_id": str(PROJECT_ID)})
        assert r3["context_version"] != r1["context_version"]

    @pytest.mark.asyncio
    async def test_empty_project_id_returns_empty(self):
        """空 project_id → 返回 {}."""
        result = await refresh_context_node({})
        assert result == {}

    @pytest.mark.asyncio
    async def test_db_exception_returns_empty(self, monkeypatch):
        """DB 异常 → 返回 {}（不阻塞 regenerate，保留 state 原值）."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def boom():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(nodes, "async_session_factory", boom)
        result = await refresh_context_node({"project_id": str(PROJECT_ID)})
        assert result == {}
