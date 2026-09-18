"""集成测试 — 全链路 mock 测试."""

import json
from typing import Any

from app.agents.state import BidState, merge_reset_on_empty


class TestFullWorkflow:
    """全工作流状态流转集成测试（P2-4：TenderState → BidState dict 语义）."""

    def test_state_lifecycle(self) -> None:
        """init → parse → confirm → outline → generate → review → export 的状态演进."""
        state: BidState = {"project_id": "test-project", "user_id": "test-user"}
        assert state.get("current_phase", "init") == "init"
        assert state.get("progress", 0.0) == 0.0

        # 模拟解析完成
        state["score_points"] = [
            {"clause_no": "1", "item": "技术方案", "score": 10, "criteria": "完整性"}
        ]
        state["current_phase"] = "confirm"
        state["progress"] = 0.15
        assert len(state["score_points"]) == 1

        # 模拟确认评分点 → 生成大纲
        state["current_phase"] = "outline"
        state["outline"] = [
            {"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]},
            {"chapter_no": "2", "title": "技术方案", "sections": ["架构", "实现"]},
        ]
        state["progress"] = 0.35
        assert len(state["outline"]) == 2

        # 模拟确认大纲 → 逐章生成（经 reducer 累加，不得覆盖已生成章节）
        state["current_phase"] = "generate"
        state["chapters"] = merge_reset_on_empty(
            state.get("chapters"), {"1": "# 项目概述\n\n## 背景\n本项目旨在..."}
        )
        state["chapters"] = merge_reset_on_empty(
            state["chapters"], {"2": "# 技术方案\n\n## 架构\n采用微服务..."}
        )
        state["progress"] = 0.75
        assert set(state["chapters"]) == {"1", "2"}, "逐章写回必须累加而非覆盖"

        # 模拟审阅
        state["review_action"] = "feedback"
        state["review_feedback"] = {"1": "建议补充项目范围"}
        state["current_phase"] = "review"
        state["progress"] = 0.85

        # 模拟导出
        state["export_storage_key"] = "test/export.docx"
        state["export_status"] = "done"
        state["current_phase"] = "done"
        state["progress"] = 1.0

        assert state.get("current_phase") == "done"
        assert state.get("progress") == 1.0
        assert state.get("export_status") == "done"

    def test_state_json_roundtrip(self) -> None:
        """状态必须可 JSON 序列化 —— 生产 checkpointer 以 JSONB 落库.

        TenderState 的 to_dict/from_dict 已随 P2-4 删除：BidState 是 TypedDict，
        本身就是 dict，序列化由 langgraph checkpointer 直接完成。此处固化的契约是
        「任何声明字段都只允许 JSON 原生类型」（不得混入 datetime/UUID/ORM 对象）。
        """
        sample: dict[str, Any] = {
            "project_id": "p1",
            "user_id": "u1",
            "score_points": [{"clause_no": "1", "item": "技术方案", "score": 10}],
            "project_name": "测试项目",
            "tender_no": "TN-2026-001",
            "industry": "公路",
            "glossary": [{"term": "TOCC", "canonical": "TOCC", "desc": "交通运行协调中心"}],
            "context_version": "v1",
            "outline_context_version": "v1",
            "outline": [{"chapter_no": "1", "title": "项目概述", "sections": ["背景"]}],
            "mounted_doc_ids": None,
            "mounted_kb_ids": ["kb-1"],
            "chapters": {"1": "# 项目概述"},
            "current_chapter": "1",
            "retrieved_context": "参考资料",
            "retrieved_citations": [{"chunk_id": "c1", "doc_title": "招标文件", "page_no": 3}],
            "validate_retries": 0,
            "validation_ok": True,
            "disqualification_risk": False,
            "chapter_summaries": {"1": {"title": "项目概述", "summary": "摘要"}},
            "consistency_issues": [
                {"chapter_no": "1", "type": "术语", "description": "不一致", "fixable": True}
            ],
            "consistency_retried": False,
            "review_action": "approved",
            "review_feedback": {"1": "补充范围说明"},
            "export_options": None,
            "export_storage_key": "p1/export/test.docx",
            "export_status": "done",
            "current_phase": "done",
            "error": "",
            "progress": 1.0,
            "regenerate_requested": False,
            "routes_snapshot": {"write": {"model": "mock", "temperature": 0.3}},
            "web_search_enabled": False,
        }
        assert set(sample) == set(BidState.__annotations__), {
            "样例未覆盖全部声明字段": sorted(set(BidState.__annotations__) ^ set(sample))
        }

        dumped = json.dumps(sample, ensure_ascii=False)
        assert json.loads(dumped) == sample


class TestChunkingIntegration:
    """分块集成测试."""

    def test_large_document_chunking(self) -> None:
        """大文档分块测试."""
        from app.services.llm.rag_service import chunk_text

        # 模拟 10000 字符的文档
        text = "这是一段测试文本。" * 556  # ~10000 字符
        chunks = chunk_text(text, chunk_size=500, overlap=50)

        assert len(chunks) > 10
        assert all(len(c) <= 500 for c in chunks)
        # 验证内容覆盖
        combined = "".join(chunks)
        assert "测试文本" in combined

    def test_empty_document_chunking(self) -> None:
        """空文档分块返回空."""
        from app.services.llm.rag_service import chunk_text

        assert chunk_text("") == []
        assert chunk_text("   \n\n  ") == []


class TestPromptIntegration:
    """提示词模板集成测试."""

    def test_all_templates_loadable(self) -> None:
        """所有提示词模板可正常加载."""
        from app.services.infra.prompt_loader import (
            load_chapter_prompt,
            load_outline_prompt,
            load_parse_prompt,
            load_review_prompt,
        )

        # parse
        system, user = load_parse_prompt("测试招标文本")
        assert system
        assert "测试招标文本" in user

        # outline
        system, user = load_outline_prompt(
            [{"clause_no": "1", "item": "方案", "score": 10}],
        )
        assert system
        assert "方案" in user

        # chapter
        _system, user = load_chapter_prompt("系统架构", ["总体设计"], "参考资料", "评分点", "")
        assert "系统架构" in user

        # review
        _system, user = load_review_prompt("章节摘要", "评分点")
        assert "章节摘要" in user
