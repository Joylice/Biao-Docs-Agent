"""阶段三 TDD 红：eval/tasks.py 三项评测任务（extraction/coverage/retrieval）."""

from pathlib import Path

import pytest

from eval import tasks
from eval.dataset import DatasetError

DATASETS_DIR = Path(__file__).resolve().parents[2] / "eval" / "datasets"


@pytest.fixture(autouse=True)
def _mock_llm_available(monkeypatch):
    """默认放行：mock 开启 → LLM/Embedding 可用（具体用例可覆盖）."""

    async def _mock_true(*args, **kwargs):
        return True

    monkeypatch.setattr(tasks.settings_service, "is_mock_enabled", _mock_true)


# ── extraction：评分点提取准召率 ──


def _extraction_dataset() -> dict:
    return {
        "id": "d1",
        "name": "样本",
        "tender_text": "招标文本",
        "gold": {
            "score_points": [
                {"clause_no": "3.2.1", "item": "技术方案完整性"},
                {"clause_no": "3.2.2", "item": "项目实施计划"},
            ],
            "tech_requirements": [],
        },
    }


class TestRunExtraction:
    async def test_full_hit(self, monkeypatch):
        async def _parse(text):
            return [
                {"clause_no": "3.2.1", "item": "技术方案完整性"},
                {"clause_no": "3.2.2", "item": "项目实施计划"},
            ]

        result = await tasks.run_extraction([_extraction_dataset()], parse_fn=_parse)
        assert result.status == "ok"
        assert result.metrics["f1"] == 1.0
        assert result.metrics["precision"] == 1.0
        assert result.metrics["recall"] == 1.0

    async def test_partial_match(self, monkeypatch):
        async def _parse(text):
            return [
                {"clause_no": "3.2.1", "item": "技术方案完整性"},
                {"clause_no": "9.9.9", "item": "幻觉条目"},
            ]

        result = await tasks.run_extraction([_extraction_dataset()], parse_fn=_parse)
        assert result.metrics["precision"] == pytest.approx(0.5)
        assert result.metrics["recall"] == pytest.approx(0.5)

    async def test_empty_datasets_skipped(self):
        result = await tasks.run_extraction([])
        assert result.status == "skipped"

    async def test_skip_when_llm_unavailable(self, monkeypatch):
        async def _mock_false(*args, **kwargs):
            return False

        async def _no_config():
            return None

        monkeypatch.setattr(tasks.settings_service, "is_mock_enabled", _mock_false)
        monkeypatch.setattr(tasks.settings_service, "get_runtime_config", _no_config)
        result = await tasks.run_extraction([_extraction_dataset()])
        assert result.status == "skipped"
        assert "LLM" in result.note

    async def test_default_parse_fn_uses_parse_service(self, monkeypatch):
        """默认提取实现内部调 parse_service 并解包 score_points."""
        calls = []

        async def _fake_parse(text, include_tech_requirements=True):
            calls.append((text, include_tech_requirements))
            from app.services.parse_service import ParsedTender

            return ParsedTender(
                score_points=[{"clause_no": "3.2.1", "item": "技术方案完整性"}],
                tech_requirements=[],
            )

        import app.services.parse_service as parse_service_mod

        monkeypatch.setattr(parse_service_mod, "parse_tender_with_llm", _fake_parse)
        result = await tasks.run_extraction([_extraction_dataset()])
        assert calls == [("招标文本", False)]
        assert result.metrics["recall"] == pytest.approx(0.5)


# ── coverage：方案评分点覆盖 ──


class TestRunCoverage:
    async def test_seed_dataset_full_coverage(self):
        import json

        data = json.loads(
            (DATASETS_DIR / "coverage" / "sample_001_synthetic.json").read_text(encoding="utf-8")
        )
        result = await tasks.run_coverage([data])
        assert result.status == "ok"
        assert result.metrics["coverage_rate"] == 1.0  # 未确认评分点不计入
        assert result.details[0]["uncovered_count"] == 0

    async def test_partial_coverage(self):
        data = {
            "id": "d1",
            "score_points": [
                {"clause_no": "1.1", "item": "A", "confirmed": True},
                {"clause_no": "1.2", "item": "B", "confirmed": True},
            ],
            "outline": [{"chapter_no": 1, "title": "章", "covered_clauses": ["1.1"]}],
        }
        result = await tasks.run_coverage([data])
        assert result.metrics["coverage_rate"] == pytest.approx(0.5)
        assert result.details[0]["uncovered_count"] == 1

    async def test_empty_datasets_skipped(self):
        result = await tasks.run_coverage([])
        assert result.status == "skipped"


# ── retrieval：检索质量 ──


class TestRunRetrieval:
    def _retrieval_dataset(self) -> dict:
        return {
            "id": "d1",
            "docs": [{"doc_id": "d1", "title": "文档", "chunks": ["内容"]}],
            "queries": [
                {"query": "查询一", "relevant_doc_ids": ["d1"]},
                {"query": "查询二", "relevant_doc_ids": ["d1"]},
            ],
        }

    async def test_perfect_ranking(self):
        async def _search(dataset, query):
            return ["d1", "d2"]

        result = await tasks.run_retrieval([self._retrieval_dataset()], search_fn=_search)
        assert result.status == "ok"
        assert result.metrics["recall_at_8"] == 1.0
        assert result.metrics["mrr"] == 1.0

    async def test_miss_query_counts_zero(self):
        async def _search(dataset, query):
            return ["d2"]

        result = await tasks.run_retrieval([self._retrieval_dataset()], search_fn=_search)
        assert result.metrics["recall_at_8"] == 0.0
        assert result.metrics["mrr"] == 0.0

    async def test_empty_datasets_skipped(self):
        result = await tasks.run_retrieval([])
        assert result.status == "skipped"

    async def test_skip_when_embedding_unavailable(self, monkeypatch):
        async def _mock_false(*args, **kwargs):
            return False

        async def _no_config():
            return None

        monkeypatch.setattr(tasks.settings_service, "is_mock_enabled", _mock_false)
        monkeypatch.setattr(tasks.settings_service, "get_runtime_config", _no_config)
        result = await tasks.run_retrieval([self._retrieval_dataset()])
        assert result.status == "skipped"
        assert "Embedding" in result.note

    async def test_invalid_dataset_dir_raises(self, tmp_path):
        with pytest.raises(DatasetError):
            await tasks.run_retrieval_from_dir(tmp_path / "missing")
