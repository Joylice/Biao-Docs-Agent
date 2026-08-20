"""worker 任务测试 — task_parse_tender 项目信息覆盖副作用防护."""

import uuid

import pytest

from app.models.document import Document
from app.models.project import Project
from app.services.parse_service import ParsedTender
from tests.agents.test_graph import FakeDB
from worker.tasks import task_parse_tender

PROJECT_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()
ORIGINAL_NAME = "智慧城市管理平台"
ORIGINAL_TENDER_NO = "TN-2026-001"


class WorkerFakeDB(FakeDB):
    """FakeDB 补充 commit（task_parse_tender 需要提交事务）与 DELETE 语句记录."""

    def __init__(self, rows_by_table: dict | None = None) -> None:
        super().__init__(rows_by_table)
        self.committed = False
        self.executed_statements: list = []

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, stmt):
        self.executed_statements.append(stmt)
        # DELETE 语句无实体描述，直接返回空结果
        if str(stmt).lstrip().upper().startswith("DELETE"):
            from tests.agents.test_graph import FakeScalarResult

            return FakeScalarResult([])
        return await super().execute(stmt)


def _make_db(project: Project) -> WorkerFakeDB:
    doc = Document(
        id=DOC_ID,
        project_id=PROJECT_ID,
        doc_type="tender",
        title="招标文件.pdf",
        storage_key=f"{PROJECT_ID}/tender.pdf",
        status="uploaded",
    )
    return WorkerFakeDB({Document: [doc], Project: [project]})


def _make_project() -> Project:
    return Project(
        id=PROJECT_ID,
        owner_id=uuid.uuid4(),
        name=ORIGINAL_NAME,
        tender_no=ORIGINAL_TENDER_NO,
    )


@pytest.fixture
def parse_env(monkeypatch):
    """mock 存储下载/文本提取/结果保存，仅 parse_tender_with_llm 返回值由用例注入."""
    from app.core import database
    from app.services import parse_service, storage_service

    state: dict = {}

    def make_session_factory(db: WorkerFakeDB):
        def factory():
            return db

        return factory

    async def fake_extract(_content: bytes, _filename: str) -> str:
        return "招标文件正文"

    async def fake_save(db, project_id, doc_id, parsed):
        return 1, 1

    def fake_download(_key: str) -> bytes:
        return b"%PDF-fake"

    monkeypatch.setattr(parse_service, "extract_tender_text", fake_extract)
    monkeypatch.setattr(parse_service, "save_parse_result", fake_save)
    monkeypatch.setattr(storage_service, "download_file", fake_download)

    state["patch_db"] = lambda db: monkeypatch.setattr(
        database, "async_session_factory", make_session_factory(db)
    )
    state["patch_llm"] = lambda parsed: monkeypatch.setattr(
        parse_service,
        "parse_tender_with_llm",
        _fake_llm(parsed),
    )
    return state


def _fake_llm(parsed: ParsedTender):
    async def fake_parse(_text: str, include_tech_requirements: bool = True) -> ParsedTender:
        return parsed

    return fake_parse


class TestTaskParseTenderProjectNameGuard:
    """解析结果覆盖项目名/编号的副作用防护."""

    @pytest.mark.asyncio
    async def test_mock_placeholder_does_not_overwrite(self, parse_env) -> None:
        """mock 占位值（'mock'）不得覆盖真实项目名/编号."""
        project = _make_project()
        db = _make_db(project)
        parse_env["patch_db"](db)
        parse_env["patch_llm"](
            ParsedTender(
                score_points=[{"clause_no": "1", "item": "方案完整性"}],
                tech_requirements=[{"seq": 1, "description": "高可用"}],
                project_name="mock",
                tender_no="mock",
            )
        )

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID))
        assert result["status"] == "success"
        assert project.name == ORIGINAL_NAME, "mock 占位值不应污染项目名"
        assert project.tender_no == ORIGINAL_TENDER_NO

    @pytest.mark.asyncio
    async def test_empty_values_do_not_overwrite(self, parse_env) -> None:
        """空值不得覆盖真实项目名/编号."""
        project = _make_project()
        db = _make_db(project)
        parse_env["patch_db"](db)
        parse_env["patch_llm"](
            ParsedTender(
                score_points=[],
                tech_requirements=[],
                project_name=None,
                tender_no="",
            )
        )

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID))
        assert result["status"] == "success"
        assert project.name == ORIGINAL_NAME
        assert project.tender_no == ORIGINAL_TENDER_NO

    @pytest.mark.asyncio
    async def test_valid_parsed_values_overwrite(self, parse_env) -> None:
        """有效解析值正常覆盖项目名/编号."""
        project = _make_project()
        db = _make_db(project)
        parse_env["patch_db"](db)
        parse_env["patch_llm"](
            ParsedTender(
                score_points=[{"clause_no": "1", "item": "方案完整性"}],
                tech_requirements=[],
                project_name="解析出的项目名称",
                tender_no="TN-2026-888",
            )
        )

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID))
        assert result["status"] == "success"
        assert project.name == "解析出的项目名称"
        assert project.tender_no == "TN-2026-888"
        assert db.committed


class TestTaskParseTenderIdempotentCleanup:
    """解析任务保存前清理该文档旧评分点（幂等，防并发 reparse 数据翻倍）."""

    @pytest.mark.asyncio
    async def test_parse_cleans_old_score_points_before_save(
        self, parse_env, monkeypatch
    ) -> None:
        """保存新结果前必须已对该文档旧评分点发起 DELETE（按 doc_id 限定）."""
        from app.services import parse_service

        db = _make_db(_make_project())
        parse_env["patch_db"](db)
        parse_env["patch_llm"](
            ParsedTender(
                score_points=[{"clause_no": "1", "item": "方案完整性"}],
                tech_requirements=[],
                project_name=None,
                tender_no=None,
            )
        )

        seen_delete_before_save: list[bool] = []

        async def tracking_save(_db, _project_id, _doc_id, _parsed):
            deletes = [
                str(s)
                for s in _db.executed_statements
                if str(s).lstrip().upper().startswith("DELETE")
            ]
            seen_delete_before_save.append(len(deletes) > 0)
            return 1, 1

        monkeypatch.setattr(parse_service, "save_parse_result", tracking_save)

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID))
        assert result["status"] == "success"
        assert seen_delete_before_save == [True], "保存新结果前必须先清理该文档旧评分点"

        # 清理语句限定本文档（score_points + doc_id 条件），避免误删同项目其他文档
        delete_stmts = [
            str(s)
            for s in db.executed_statements
            if str(s).lstrip().upper().startswith("DELETE")
        ]
        assert len(delete_stmts) == 1
        assert "score_points" in delete_stmts[0]
        assert "doc_id" in delete_stmts[0]


class TestTaskParseTenderScorePointsOnly:
    """重新解析（score_points_only=True）跳过技术需求提取."""

    @pytest.mark.asyncio
    async def test_score_points_only_disables_tech_requirements(
        self, parse_env, monkeypatch
    ) -> None:
        """score_points_only=True 时 LLM 解析应收到 include_tech_requirements=False."""
        from app.services import parse_service

        parse_env["patch_db"](_make_db(_make_project()))

        calls: list[bool] = []

        async def fake_parse(_text: str, include_tech_requirements: bool = True):
            calls.append(include_tech_requirements)
            return ParsedTender(
                score_points=[{"clause_no": "1", "item": "方案完整性"}],
                tech_requirements=[],
                project_name=None,
                tender_no=None,
            )

        monkeypatch.setattr(parse_service, "parse_tender_with_llm", fake_parse)

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID), score_points_only=True)
        assert result["status"] == "success"
        assert calls == [False], "重新解析应跳过技术需求提取"

    @pytest.mark.asyncio
    async def test_default_keeps_tech_requirements(self, parse_env, monkeypatch) -> None:
        """首次解析（默认）仍提取技术需求."""
        from app.services import parse_service

        parse_env["patch_db"](_make_db(_make_project()))

        calls: list[bool] = []

        async def fake_parse(_text: str, include_tech_requirements: bool = True):
            calls.append(include_tech_requirements)
            return ParsedTender(score_points=[], tech_requirements=[])

        monkeypatch.setattr(parse_service, "parse_tender_with_llm", fake_parse)

        result = await task_parse_tender({}, str(PROJECT_ID), str(DOC_ID))
        assert result["status"] == "success"
        assert calls == [True]
