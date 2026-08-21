"""重构期 3 结构守卫测试 — nodes 包拆分后对外符号与 monkeypatch 语义零破坏.

约束来源：既有测试大量 monkeypatch ``app.agents.nodes`` 包属性
（async_session_factory / publish_event / _upsert_section），节点实现
必须经包命名空间在调用时动态查找这些名字，本测试固化该语义。
"""

import importlib
import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import nodes

# 原 nodes.py 对外符号全集（拆分后必须继续可从 app.agents.nodes 导入）
NODE_FUNCS = [
    "parse_tender_node",
    "confirm_score_points_node",
    "generate_outline_node",
    "confirm_outline_node",
    "retrieve_node",
    "write_node",
    "validate_node",
    "consistency_check_node",
    "integrate_node",
    "review_node",
    "rewrite_node",
    "export_node",
]
ROUTES = [
    "chapter_route",
    "review_route",
    "route_after_confirm",
    "route_after_outline_confirmed",
]
HELPERS = [
    "_update_workflow",
    "_load_tender_context",
    "_upsert_skeleton",
    "_upsert_section",
    "_persist_chapter_content",
    "_clear_outline_draft",
    "_review_record",
]
CONSTANTS = [
    "MIN_CHAPTER_LENGTH",
    "MAX_VALIDATE_RETRIES",
    "STREAM_FLUSH_CHARS",
    "STREAM_FLUSH_SECS",
]
REEXPORTS = NODE_FUNCS + ROUTES + HELPERS + CONSTANTS + ["logger"]


class TestPackageStructure:
    def test_is_package_with_submodules(self) -> None:
        assert hasattr(nodes, "__path__"), "app.agents.nodes 应为包（原 nodes.py 已拆分为包）"
        for sub in ("parse", "outline", "chapter", "review", "_shared"):
            mod = importlib.import_module(f"app.agents.nodes.{sub}")
            assert inspect.ismodule(mod)

    @pytest.mark.parametrize("name", REEXPORTS)
    def test_symbol_reexported(self, name: str) -> None:
        assert hasattr(nodes, name), f"app.agents.nodes 缺少 re-export 符号: {name}"

    def test_patchable_runtime_names_exposed(self) -> None:
        """既有测试 patch 目标（包属性形式）必须存在."""
        assert callable(nodes.async_session_factory)
        assert callable(nodes.publish_event)
        # 服务对象属性级 patch（nodes.settings_service.is_mock_enabled 等）
        assert nodes.settings_service is not None
        assert nodes.kb_base_service is not None

    def test_graph_imports_unchanged(self) -> None:
        """graph.py 所需全部节点/路由可从包导入，图可编译."""
        from app.agents.graph import build_workflow

        workflow = build_workflow()
        assert workflow is not None


class TestRuntimeLookupPatchSemantics:
    """节点经包命名空间查找 async_session_factory / publish_event / _upsert_section."""

    @pytest.mark.asyncio
    async def test_patch_package_session_factory_affects_parse_node(self) -> None:
        called: dict = {}

        class _FakeDB:
            async def execute(self, _stmt):
                called["execute"] = True

                class _R:
                    def scalar_one_or_none(self):
                        return None

                    def scalars(self):
                        return self

                    def all(self):
                        return []

                return _R()

            async def flush(self) -> None:
                pass

            async def commit(self) -> None:
                pass

            def add(self, _obj) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                pass

        with patch.object(nodes, "async_session_factory", lambda: _FakeDB()):
            result = await nodes.parse_tender_node({"project_id": str(uuid.uuid4())})
        assert called.get("execute"), "patch nodes.async_session_factory 必须对节点生效"
        assert "error" in result  # 无评分点 → 提示先解析（行为与拆分前一致）

    @pytest.mark.asyncio
    async def test_patch_package_upsert_section_affects_persist(self) -> None:
        """test_assist_service 依赖 patch app.agents.nodes._upsert_section 生效."""
        captured: list = []

        async def fake_upsert(db, pid, section_id, title, content_md, **kwargs) -> None:
            captured.append(section_id)

        with patch.object(nodes, "_upsert_section", fake_upsert):
            await nodes._persist_chapter_content(object(), str(uuid.uuid4()), "1", "概述", "# 正文")
        assert captured == ["1"]

    @pytest.mark.asyncio
    async def test_patch_package_publish_event_affects_review_route_node(self) -> None:
        events: list = []

        async def fake_publish(_pid, event) -> None:
            events.append(event)

        class _FakeDB:
            async def execute(self, _stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return None

                return _R()

            async def flush(self) -> None:
                pass

            async def commit(self) -> None:
                pass

            def add(self, _obj) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                pass

        state = {"project_id": str(uuid.uuid4()), "chapters": {}, "outline": []}
        with (
            patch.object(nodes, "async_session_factory", lambda: _FakeDB()),
            patch.object(nodes, "publish_event", fake_publish),
        ):
            result = await nodes.integrate_node(state)
        assert result["current_phase"] == "review"
        assert any(e["type"] == "progress" for e in events), (
            "patch nodes.publish_event 必须对节点生效"
        )

    @pytest.mark.asyncio
    async def test_mock_llm_disabled_via_settings_service_object(self) -> None:
        """nodes.settings_service 对象属性级 patch（test_glossary 同风格）仍可用."""
        with patch.object(nodes.settings_service, "is_mock_enabled", AsyncMock(return_value=True)):
            assert await nodes.settings_service.is_mock_enabled() is True
