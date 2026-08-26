"""workflow_runtime 服务测试 — InMemorySaver 驱动真实图执行（LLM mock 模式）."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import nodes
from app.core.config import settings
from app.core.exceptions import BizError
from app.models.proposal import ProposalSection, ProposalSkeleton
from app.services.infra import workflow_runtime
from app.services.proposal.chapter_service import extract_chapter_summary
from tests.agents.test_graph import make_fake_db

PROJECT_ID = uuid.uuid4()
FAKE_EXPORT_KEY = f"{PROJECT_ID}/export/runtime-test.docx"


@pytest.fixture
def memory_runtime(monkeypatch):
    """注入 InMemorySaver 作为 checkpointer，用例结束清理."""
    workflow_runtime.set_saver(InMemorySaver())
    yield
    workflow_runtime.set_saver(None)


@pytest.fixture
def mock_node_deps(monkeypatch):
    """mock 节点外部依赖（DB/事件/导出），LLM 走 mock 模式."""

    async def fake_publish_event(_project_id: str, _event: dict) -> None:
        pass

    def fake_session_factory():
        return make_fake_db()

    async def fake_export_to_word(**kwargs) -> str:
        return FAKE_EXPORT_KEY

    async def fake_get_embedding(_text: str):
        return []

    async def fake_retrieve_similar(**kwargs):
        return []

    async def fake_call_llm_with_schema(**kwargs) -> dict:
        return {
            "chapters": [
                {
                    "chapter_no": "1",
                    "title": "项目概述",
                    "sections": ["背景", "目标"],
                    "covered_clauses": ["1", "2"],
                },
                {
                    "chapter_no": "2",
                    "title": "技术方案",
                    "sections": ["架构", "实现"],
                    "covered_clauses": ["3"],
                },
            ]
        }

    monkeypatch.setattr(settings, "llm_mock", True)
    monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
    monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", fake_call_llm_with_schema)
    monkeypatch.setattr("app.services.llm.rag_service.get_embedding", fake_get_embedding)
    monkeypatch.setattr("app.services.llm.rag_service.retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr("app.services.document.export_service.export_to_word", fake_export_to_word)


class TestRunAndResume:
    """run/resume 驱动真实图，HITL interrupt 逐段推进."""

    @pytest.mark.asyncio
    async def test_run_stops_at_score_points_interrupt(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """首次 run 停在评分点 interrupt，score_points 来自 DB 非硬编码空值."""
        result = await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        assert result["__interrupt__"][0].value["type"] == "confirm_score_points"

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        values = snapshot.values
        assert values["score_points"], "parse 节点应从 DB 读出评分点"
        assert values["score_points"][0]["item"] == "技术方案完整性"
        assert values["current_phase"] == "confirm"

    @pytest.mark.asyncio
    async def test_resume_advances_through_hitl_nodes(self, memory_runtime, mock_node_deps) -> None:
        """confirm → outline interrupt → review interrupt → approved 完成."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())

        # 确认评分点 → 停在大纲 interrupt
        result = await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        assert result["__interrupt__"][0].value["type"] == "confirm_outline"

        # 确认大纲 → 章节生成 → 停在审阅 interrupt
        result = await workflow_runtime.resume_workflow(PROJECT_ID, True)
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert set(result["chapters"].keys()) == {"1", "2"}

        # 审阅通过 → 导出完成
        result = await workflow_runtime.resume_workflow(PROJECT_ID, {"action": "approved"})
        assert result["export_status"] == "done"
        assert result["current_phase"] == "done"

    @pytest.mark.asyncio
    async def test_get_status_reports_phase_and_progress(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """get_status_dict 的 phase/progress/interrupt 随执行变化."""
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["phase"] == "init"
        assert status["progress"] == 0.0
        assert status["interrupt"] is None

        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["phase"] == "confirm"
        assert status["progress"] == pytest.approx(0.15)
        assert status["interrupt"]["type"] == "confirm_score_points"
        assert status["score_points"]

        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["interrupt"]["type"] == "confirm_outline"
        assert status["outline"], "mock LLM 应产出大纲"


class TestRegenerateOutline:
    """重新生成大纲（仅 confirm_outline interrupt 挂起时允许）."""

    async def _advance_to_outline_interrupt(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})

    @pytest.mark.asyncio
    async def test_regenerate_outline_updates_state_with_covered_clauses(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """重新生成后 outline 更新且携带 covered_clauses（新提示词产物）."""
        await self._advance_to_outline_interrupt()

        outline = await workflow_runtime.regenerate_outline(PROJECT_ID)
        assert len(outline) == 2
        assert outline[0]["covered_clauses"] == ["1", "2"], "新大纲应携带 covered_clauses"

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["outline"][0]["covered_clauses"] == ["1", "2"], (
            "checkpointer state 应同步更新"
        )

    @pytest.mark.asyncio
    async def test_regenerate_outline_preserves_pending_interrupt(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """重新生成后 confirm_outline interrupt 必须保留，否则工作流无法 resume（4009 卡死）."""
        await self._advance_to_outline_interrupt()

        await workflow_runtime.regenerate_outline(PROJECT_ID)

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["interrupt"] is not None, "regenerate 不得清除 pending interrupt"
        assert status["interrupt"]["type"] == "confirm_outline"

    @pytest.mark.asyncio
    async def test_regenerate_outline_syncs_state_with_new_llm_output(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """regenerate 后 checkpointer/status 必须同步 LLM 新产物，章节按新大纲生成.

        曾因 confirm_outline_node 内联调用 generate_outline_node（普通函数调用
        不经图写入 checkpoint），导致 DB 落库新大纲而 state 仍旧大纲、确认后
        章节按旧大纲生成的 DB/state 不一致缺陷。
        """
        outline_calls = {"n": 0}

        async def _call_llm_with_schema(**kwargs) -> dict:
            schema = (kwargs.get("response_format") or {}).get("json_schema", {})
            schema_name = schema.get("name", "")
            if schema_name == "outline":
                outline_calls["n"] += 1
                if outline_calls["n"] >= 2:  # 第二次（regenerate）返回全新大纲
                    return {
                        "chapters": [
                            {
                                "chapter_no": "9",
                                "title": "新生成章",
                                "sections": ["新子节"],
                                "covered_clauses": ["4.2"],
                            }
                        ]
                    }
                return {
                    "chapters": [
                        {
                            "chapter_no": "1",
                            "title": "初始章",
                            "sections": ["旧子节"],
                            "covered_clauses": ["1"],
                        }
                    ]
                }
            return {
                "chapters": [
                    {
                        "chapter_no": "1",
                        "title": "项目概述",
                        "sections": ["背景"],
                        "covered_clauses": ["1"],
                    }
                ]
            }

        monkeypatch.setattr("app.services.llm.llm_service.call_llm_with_schema", _call_llm_with_schema)
        await self._advance_to_outline_interrupt()
        assert outline_calls["n"] == 1, "初始大纲应已生成一次"

        outline = await workflow_runtime.regenerate_outline(PROJECT_ID)
        assert outline[0]["title"] == "新生成章", "regenerate 应返回 LLM 新产物"

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["outline"][0]["title"] == "新生成章", "checkpointer state 应同步新大纲"

        # 确认大纲 → 章节必须按新大纲生成（防 DB/state 不一致导致下游错乱）
        result = await workflow_runtime.resume_workflow(PROJECT_ID, True)
        assert set(result["chapters"].keys()) == {"9"}, "章节应按新大纲章节号生成"

    @pytest.mark.asyncio
    async def test_regenerate_outline_rejected_when_no_pending_interrupt(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """非 confirm_outline 挂起态重新生成被拒绝（4009）."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        # 当前挂起的是 confirm_score_points，重新生成大纲应被拒绝
        with pytest.raises(BizError) as ei:
            await workflow_runtime.regenerate_outline(PROJECT_ID)
        assert ei.value.code == 4009


class TestConfirmOutlineEdited:
    """大纲二次编辑：resume 携带编辑后 outline / mounted_doc_ids，章节按新大纲生成."""

    async def _advance_to_outline_interrupt(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})

    @pytest.mark.asyncio
    async def test_confirm_with_edited_outline_generates_new_chapters(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """编辑后大纲（改标题+增章）确认 → state.outline 替换、章节按新大纲生成."""
        edited = [
            {
                "chapter_no": "1",
                "title": "编辑后第一章",
                "sections": ["子节A"],
                "covered_clauses": ["1", "2"],
            },
            {
                "chapter_no": "2",
                "title": "编辑后第二章",
                "sections": ["子节B"],
                "covered_clauses": ["3"],
            },
            {
                "chapter_no": "3",
                "title": "新增第三章",
                "sections": ["子节C"],
                "covered_clauses": ["4"],
            },
        ]
        await self._advance_to_outline_interrupt()

        result = await workflow_runtime.resume_workflow(
            PROJECT_ID, {"confirmed": True, "outline": edited}
        )
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert result["outline"] == edited, "state.outline 应替换为编辑后大纲"
        assert set(result["chapters"].keys()) == {"1", "2", "3"}, "章节应按编辑后大纲生成"

    @pytest.mark.asyncio
    async def test_confirm_edited_outline_persists_skeleton(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """编辑后大纲确认时落库 proposal_skeletons（DB 与 state 一致）."""
        from app.models.proposal import ProposalSkeleton

        db = make_fake_db()
        monkeypatch.setattr(nodes, "async_session_factory", lambda: db)
        edited = [
            {
                "chapter_no": "1",
                "title": "编辑后标题",
                "sections": ["子节"],
                "covered_clauses": ["1"],
            }
        ]
        await self._advance_to_outline_interrupt()

        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True, "outline": edited})

        skeletons = [o for o in db.added if isinstance(o, ProposalSkeleton)]
        assert skeletons, "编辑后大纲应落库 proposal_skeletons"
        assert skeletons[-1].tree == edited

    @pytest.mark.asyncio
    async def test_confirm_with_mounted_doc_ids_updates_state(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """resume 携带 mounted_doc_ids → 写入 state（RAG 挂载配置生效）."""
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        await self._advance_to_outline_interrupt()

        await workflow_runtime.resume_workflow(
            PROJECT_ID, {"confirmed": True, "mounted_doc_ids": doc_ids}
        )

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert snapshot.values.get("mounted_doc_ids") == doc_ids


class TestRewriteAndExport:
    """章节重写与导出的状态回写."""

    async def _advance_to_review(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(PROJECT_ID, True)

    @pytest.mark.asyncio
    async def test_rewrite_chapter_merges_into_state(self, memory_runtime, mock_node_deps) -> None:
        """重写结果经 checkpointer 回写 chapters."""
        await self._advance_to_review()
        new_content = await workflow_runtime.rewrite_chapter(PROJECT_ID, "1", "补充项目范围")
        assert new_content

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        chapters = snapshot.values["chapters"]
        assert chapters["1"] == new_content
        assert "2" in chapters, "其余章节不受影响"

    @pytest.mark.asyncio
    async def test_rewrite_missing_chapter_raises(self, memory_runtime, mock_node_deps) -> None:
        await self._advance_to_review()
        with pytest.raises(BizError):
            await workflow_runtime.rewrite_chapter(PROJECT_ID, "99", "意见")

    @pytest.mark.asyncio
    async def test_export_workflow_reuses_export_node(self, memory_runtime, mock_node_deps) -> None:
        """导出复用图内 export 节点逻辑，结果回写 state."""
        await self._advance_to_review()
        result = await workflow_runtime.export_workflow(PROJECT_ID)
        assert result["export_status"] == "done"
        assert result["export_storage_key"] == FAKE_EXPORT_KEY

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert status["export_storage_key"] == FAKE_EXPORT_KEY

    @pytest.mark.asyncio
    async def test_export_before_chapters_raises(self, memory_runtime, mock_node_deps) -> None:
        with pytest.raises(BizError):
            await workflow_runtime.export_workflow(PROJECT_ID)


class TestGuardAndInit:
    """后台任务异常可见性 + checkpointer 未初始化."""

    @pytest.mark.asyncio
    async def test_background_error_written_to_state(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """后台任务异常写入 state.error（可经 status 观测）."""

        async def boom(project_id, user_id):
            raise RuntimeError("模拟图执行崩溃")

        monkeypatch.setattr(workflow_runtime, "run_workflow", boom)
        task = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        await task

        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert "模拟图执行崩溃" in status["error"]

    @pytest.mark.asyncio
    async def test_no_saver_raises_biz_error(self, memory_runtime) -> None:
        workflow_runtime.set_saver(None)
        with pytest.raises(BizError):
            await workflow_runtime.get_state(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_duplicate_start_rejected_and_slot_released(
        self, memory_runtime, monkeypatch
    ) -> None:
        """同一项目在途时重复 start 被拒（4009）；任务结束后槽位释放可再启动."""
        release = asyncio.Event()

        async def hang(project_id, user_id):
            await release.wait()
            return {}

        monkeypatch.setattr(workflow_runtime, "run_workflow", hang)
        task = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())

        with pytest.raises(BizError) as ei:
            workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        assert ei.value.code == 4009

        release.set()
        await task

        # 任务结束后槽位释放：可以再次启动
        monkeypatch.setattr(workflow_runtime, "run_workflow", AsyncMock(return_value={}))
        task2 = workflow_runtime.start_workflow_in_background(PROJECT_ID, uuid.uuid4())
        await task2

    @pytest.mark.asyncio
    async def test_init_checkpointer_closes_pool_when_setup_fails(self, monkeypatch) -> None:
        """pool.open() 成功后 saver.setup() 抛异常 → 已打开的 pool 被关闭，无连接泄漏.

        注：conftest 将 init_checkpointer 替换为跳过桩，这里调用其保留的原实现。
        """
        pool = MagicMock()
        pool.open = AsyncMock()
        pool.close = AsyncMock()
        monkeypatch.setattr(
            "langgraph.checkpoint.postgres.aio.AsyncConnectionPool", lambda *a, **k: pool
        )

        saver = MagicMock()
        saver.setup = AsyncMock(side_effect=RuntimeError("模拟 checkpointer 建表失败"))
        monkeypatch.setattr(
            workflow_runtime, "get_async_postgres_saver", lambda: lambda conn: saver
        )
        monkeypatch.setattr(workflow_runtime, "_saver", None, raising=False)
        monkeypatch.setattr(workflow_runtime, "_pool", None, raising=False)

        await workflow_runtime._init_checkpointer_impl()

        saver.setup.assert_awaited_once()
        pool.close.assert_awaited_once()
        assert workflow_runtime._saver is None
        assert workflow_runtime._pool is None


class TestOutlineDraftClear:
    """确认大纲后自动清除草稿（防陈旧草稿下次误恢复）."""

    @pytest.mark.asyncio
    async def test_confirm_outline_clears_draft(self, memory_runtime, monkeypatch) -> None:
        """confirm_outline 确认（resume confirmed）后，proposal_skeletons.draft 置空."""
        skeleton = ProposalSkeleton(project_id=PROJECT_ID, tree=[])
        skeleton.draft = [{"chapter_no": "1", "title": "旧草稿"}]

        async def fake_publish_event(_project_id: str, _event: dict) -> None:
            pass

        def fake_session_factory():
            db = make_fake_db()
            db.rows_by_table[ProposalSkeleton] = [skeleton]
            return db

        async def fake_call_llm_with_schema(**kwargs) -> dict:
            return {
                "chapters": [
                    {
                        "chapter_no": "1",
                        "title": "项目概述",
                        "sections": ["背景"],
                        "covered_clauses": ["1"],
                    }
                ]
            }

        monkeypatch.setattr(settings, "llm_mock", True)
        monkeypatch.setattr(nodes, "async_session_factory", fake_session_factory)
        monkeypatch.setattr(nodes, "publish_event", fake_publish_event)
        monkeypatch.setattr(
            "app.services.llm.llm_service.call_llm_with_schema", fake_call_llm_with_schema
        )

        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        # 确认评分点 → 推进到 confirm_outline interrupt
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert (status.get("interrupt") or {}).get("type") == "confirm_outline"

        # 确认（携带编辑后的大纲）→ 草稿被清除
        await workflow_runtime.resume_workflow_in_background(
            PROJECT_ID,
            {
                "confirmed": True,
                "outline": [{"chapter_no": "1", "title": "确认后大纲", "sections": []}],
            },
        )
        status = await workflow_runtime.get_status_dict(PROJECT_ID)
        assert (status.get("interrupt") or {}).get("type") == "review_request"
        assert skeleton.draft is None, "确认大纲后应清除草稿"
        assert skeleton.tree[0]["title"] == "确认后大纲"


class TestSaveSectionEdit:
    """人工编辑章节保存：state 回写（chapters + 摘要重算）+ proposal_sections 落库."""

    async def _advance_to_review(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(PROJECT_ID, True)

    @pytest.mark.asyncio
    async def test_save_section_edit_updates_state_and_db(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """编辑内容回写 state.chapters、摘要重算，proposal_sections 落库 status=review."""
        await self._advance_to_review()
        db = make_fake_db()
        new_content = "# 项目概述\n\n人工编辑后的完整内容，用于校验保存通道。"

        await workflow_runtime.save_section_edit(db, PROJECT_ID, "1", new_content)

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert snapshot.values["chapters"]["1"] == new_content
        assert snapshot.values["chapter_summaries"]["1"]["summary"] == extract_chapter_summary(
            new_content
        ), "保存后应重算章节摘要（保持章间上下文链路有效）"

        sections = [o for o in db.added if isinstance(o, ProposalSection)]
        assert sections, "编辑内容应落库 proposal_sections"
        assert sections[-1].section_id == "1"
        assert sections[-1].content_md == new_content
        assert sections[-1].status == "review"

    @pytest.mark.asyncio
    async def test_save_section_edit_upserts_existing_row(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """已存在的 proposal_sections 行更新而非重复插入（upsert）."""
        await self._advance_to_review()
        db = make_fake_db()
        existing = ProposalSection(
            project_id=PROJECT_ID,
            section_id="1",
            title="旧标题",
            content_md="旧内容",
            status="draft",
        )
        db.rows_by_table[ProposalSection] = [existing]

        await workflow_runtime.save_section_edit(db, PROJECT_ID, "1", "覆盖后的内容")

        assert existing.content_md == "覆盖后的内容"
        assert existing.status == "review"
        assert existing not in db.added, "已存在行应原地更新而非新增"

    @pytest.mark.asyncio
    async def test_save_section_edit_missing_chapter_raises(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """未生成章节保存被拒（4004）."""
        await self._advance_to_review()
        db = make_fake_db()
        with pytest.raises(BizError) as ei:
            await workflow_runtime.save_section_edit(db, PROJECT_ID, "99", "内容")
        assert ei.value.code == 4004

    @pytest.mark.asyncio
    async def test_save_section_edit_subsection_merges_parent(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """子节编号编辑：子节行更新（status=review）并重建父章全文回写 state."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        # 确认嵌套大纲（含子节）→ 生成 → 审阅
        await workflow_runtime.resume_workflow(
            PROJECT_ID,
            {
                "confirmed": True,
                "outline": [
                    {
                        "chapter_no": "1",
                        "title": "项目概述",
                        "sections": [{"title": "背景"}, {"title": "目标"}],
                    }
                ],
            },
        )
        row12 = ProposalSection(
            project_id=PROJECT_ID,
            section_id="1.2",
            title="目标",
            content_md="旧目标",
            status="draft",
        )
        db = make_fake_db()
        db.rows_by_table[ProposalSection] = [row12]

        await workflow_runtime.save_section_edit(db, PROJECT_ID, "1.2", "新目标内容")

        assert row12.content_md == "新目标内容"
        assert row12.status == "review"
        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert snapshot.values["chapters"]["1"] == "新目标内容", "父章全文应由子节行重建"


class TestGenerateChapterDraft:
    """分工编制初稿：LLM（mock 模式）生成 + state 回写 + proposal_sections 落库 draft."""

    async def _advance_to_outline_confirmed(self) -> None:
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(PROJECT_ID, True)

    @pytest.mark.asyncio
    async def test_generate_draft_writes_state_and_section(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """初稿回写 state.chapters 与摘要，proposal_sections 落库 status=draft."""
        await self._advance_to_outline_confirmed()
        db = make_fake_db()
        monkeypatch.setattr("app.core.database.async_session_factory", lambda: db)

        content = await workflow_runtime.generate_chapter_draft(PROJECT_ID, "1")

        assert content, "mock 模式应产出确定性初稿"
        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert snapshot.values["chapters"]["1"] == content
        assert snapshot.values["chapter_summaries"]["1"]["summary"], "初稿应重算章节摘要"
        sections = [o for o in db.added if isinstance(o, ProposalSection)]
        assert sections, "初稿应落库 proposal_sections"
        assert sections[-1].section_id == "1"
        assert sections[-1].status == "draft"

    @pytest.mark.asyncio
    async def test_generate_draft_missing_chapter_raises(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """大纲中不存在的章节 → 4004."""
        await self._advance_to_outline_confirmed()
        with pytest.raises(BizError) as ei:
            await workflow_runtime.generate_chapter_draft(PROJECT_ID, "99")
        assert ei.value.code == 4004

    @pytest.mark.asyncio
    async def test_generate_draft_subsection_routes_to_parent(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """子节编号初稿：重定向父章生成，state 写父章，子节行落库."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(
            PROJECT_ID,
            {
                "confirmed": True,
                "outline": [
                    {
                        "chapter_no": "1",
                        "title": "项目概述",
                        "sections": [{"title": "背景"}, {"title": "目标"}],
                    }
                ],
            },
        )
        db = make_fake_db()
        monkeypatch.setattr("app.core.database.async_session_factory", lambda: db)

        content = await workflow_runtime.generate_chapter_draft(PROJECT_ID, "1.1")

        assert content, "子节初稿应非空（命中子节片段或降级整章）"
        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert "1" in snapshot.values["chapters"], "子节生成应写父章全文到 state"
        sections = [o for o in db.added if isinstance(o, ProposalSection)]
        assert any(s.section_id.startswith("1.") for s in sections), "子节行应落库"


class TestDivisionDrivenMode:
    """分工驱动编制模式（2026-08-25）：start_generation=False → 停靠 wait_division."""

    @pytest.mark.asyncio
    async def test_confirm_outline_start_generation_false_stops_at_wait_division(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """确认大纲携带 start_generation=False → 停在 wait_division interrupt，不进入章节生成."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})

        result = await workflow_runtime.resume_workflow(
            PROJECT_ID, {"confirmed": True, "start_generation": False}
        )
        assert result["__interrupt__"][0].value["type"] == "wait_division", (
            "start_generation=False 应停在待分工 interrupt"
        )
        assert result["current_phase"] == "division"
        assert not result.get("chapters"), "分工驱动模式不自动生成章节"

    @pytest.mark.asyncio
    async def test_confirm_outline_default_still_generates(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """resume 不带 start_generation（旧测试语义）→ 仍进入章节生成（向后兼容）."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})

        result = await workflow_runtime.resume_workflow(PROJECT_ID, True)
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert set(result["chapters"].keys()) == {"1", "2"}

    @pytest.mark.asyncio
    async def test_wait_division_resume_advances_to_review(
        self, memory_runtime, mock_node_deps
    ) -> None:
        """分工编制完成（章节已回写 state）→ resume wait_division → 整合审阅."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(
            PROJECT_ID, {"confirmed": True, "start_generation": False}
        )

        # 模拟分工审核通过已回写两个章节到 state
        content = "# 人工编制内容\n\n" + "分工人员编制的内容。\n" * 20
        await workflow_runtime.update_state(
            PROJECT_ID,
            {
                "chapters": {"1": content, "2": content},
                "chapter_summaries": {
                    "1": {"title": "项目概述", "summary": "摘要1"},
                    "2": {"title": "技术方案", "summary": "摘要2"},
                },
            },
        )

        result = await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        assert result["__interrupt__"][0].value["type"] == "review_request"
        assert result["current_phase"] == "review"
        assert set(result["chapters"].keys()) == {"1", "2"}
        assert "人工编制内容" in result["chapters"]["1"], "审阅内容应为分工编制产物"

    @pytest.mark.asyncio
    async def test_sync_approved_chapter_writes_state_and_db(
        self, memory_runtime, mock_node_deps, monkeypatch
    ) -> None:
        """审核通过回写：state.chapters + proposal_sections（status=approved）+ 摘要."""
        await workflow_runtime.run_workflow(PROJECT_ID, uuid.uuid4())
        await workflow_runtime.resume_workflow(PROJECT_ID, {"confirmed": True})
        await workflow_runtime.resume_workflow(
            PROJECT_ID, {"confirmed": True, "start_generation": False}
        )

        db = make_fake_db()
        monkeypatch.setattr("app.core.database.async_session_factory", lambda: db)

        content = "# 分工编制\n\n负责人编制的内容，满足长度要求。\n" * 15
        await workflow_runtime.sync_approved_chapter(
            db, PROJECT_ID, "1", content, "<h1>分工编制</h1>"
        )

        snapshot = await workflow_runtime.get_state(PROJECT_ID)
        assert "1" in snapshot.values["chapters"], "审核通过应回写 state.chapters"
        assert snapshot.values["chapters"]["1"] == content
        assert "1" in snapshot.values.get("chapter_summaries", {})

        sections = [o for o in db.added if isinstance(o, ProposalSection)]
        chapter_row = next((s for s in sections if s.section_id == "1"), None)
        assert chapter_row is not None, "章级行应落库 proposal_sections"
        assert chapter_row.status == "approved"
        assert chapter_row.content_md == content
