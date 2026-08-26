"""集成测试 — 全链路 mock 测试."""

import pytest

from app.agents.state import TenderState


class TestFullWorkflow:
    """全工作流集成测试（mock LLM/DB/Storage）."""

    @pytest.mark.asyncio
    async def test_state_lifecycle(self) -> None:
        """测试状态生命周期: init → parse → confirm → generate → review → export."""
        # 初始状态
        state = TenderState(project_id="test-project", user_id="test-user")
        assert state.current_phase == "init"
        assert state.progress == 0.0

        # 模拟解析完成
        state.current_phase = "confirm"
        state.score_points = [
            {"clause_no": "1", "item": "技术方案", "score": 10, "criteria": "完整性"}
        ]
        state.tech_requirements = [{"seq": 1, "description": "支持高可用", "category": "架构"}]
        state.progress = 0.15
        assert state.current_phase == "confirm"
        assert len(state.score_points) == 1

        # 模拟确认评分点
        state.score_points_confirmed = True
        state.current_phase = "outline"

        # 模拟大纲生成
        state.outline = [
            {"chapter_no": "1", "title": "项目概述", "sections": ["背景", "目标"]},
            {"chapter_no": "2", "title": "技术方案", "sections": ["架构", "实现"]},
        ]
        state.progress = 0.35
        assert len(state.outline) == 2

        # 模拟确认大纲
        state.outline_confirmed = True
        state.current_phase = "generate"

        # 模拟章节生成
        state.chapters = {
            "1": "# 项目概述\n\n## 背景\n本项目旨在...",
            "2": "# 技术方案\n\n## 架构\n采用微服务...",
        }
        state.progress = 0.75
        assert len(state.chapters) == 2

        # 模拟审阅
        state.review_comments = [
            {
                "chapter_no": "1",
                "comment": "建议补充项目范围",
                "action": "revise",
                "severity": "warning",
            }
        ]
        state.current_phase = "review"
        state.progress = 0.85

        # 模拟导出
        state.export_storage_key = "test/export.docx"
        state.export_status = "done"
        state.current_phase = "done"
        state.progress = 1.0

        # 验证最终状态
        assert state.current_phase == "done"
        assert state.progress == 1.0
        assert state.export_status == "done"

    @pytest.mark.asyncio
    async def test_state_serialization_roundtrip(self) -> None:
        """测试状态序列化/反序列化."""
        original = TenderState(
            project_id="p1",
            user_id="u1",
            current_phase="generate",
            progress=0.5,
            score_points=[{"clause_no": "1", "item": "test"}],
            outline=[{"chapter_no": "1", "title": "概述"}],
            chapters={"1": "content"},
        )

        # 序列化
        d = original.to_dict()
        assert isinstance(d, dict)
        assert d["project_id"] == "p1"

        # 反序列化
        restored = TenderState.from_dict(d)
        assert restored.project_id == original.project_id
        assert restored.current_phase == original.current_phase
        assert restored.progress == original.progress
        assert restored.score_points == original.score_points
        assert restored.chapters == original.chapters


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
            [{"description": "高可用", "category": "架构"}],
        )
        assert system
        assert "方案" in user

        # chapter
        _system, user = load_chapter_prompt(
            "系统架构", ["总体设计"], "参考资料", "评分点", "技术需求"
        )
        assert "系统架构" in user

        # review
        _system, user = load_review_prompt("章节摘要", "评分点")
        assert "章节摘要" in user
