"""阶段二 TDD 红：eval/dataset.py 数据集 schema 校验与目录加载 + 种子样本自检."""

import json
from pathlib import Path

import pytest

from eval.dataset import (
    DatasetError,
    load_coverage_datasets,
    load_extraction_datasets,
    load_retrieval_datasets,
    validate_coverage,
    validate_extraction,
    validate_retrieval,
)

DATASETS_DIR = Path(__file__).resolve().parents[2] / "eval" / "datasets"


def _valid_extraction() -> dict:
    return {
        "id": "sample_001",
        "name": "合成样本",
        "tender_text": "3.2.1 技术方案完整性……",
        "gold": {
            "score_points": [
                {
                    "clause_no": "3.2.1",
                    "item": "技术方案完整性",
                    "criteria": "优得5分",
                    "is_star": False,
                }
            ],
            "tech_requirements": [
                {"seq": 1, "description": "支持国产化部署", "category": "功能需求"}
            ],
        },
    }


def _valid_retrieval() -> dict:
    return {
        "id": "sample_001",
        "docs": [{"doc_id": "d1", "title": "运维手册", "chunks": ["提供7×24小时运维支持"]}],
        "queries": [{"query": "运维支持承诺", "relevant_doc_ids": ["d1"]}],
    }


# ── extraction schema 校验 ──


class TestValidateExtraction:
    def test_valid(self):
        assert validate_extraction(_valid_extraction()) is not None

    @pytest.mark.parametrize("missing", ["id", "name", "tender_text", "gold"])
    def test_missing_top_level_key(self, missing):
        data = _valid_extraction()
        data.pop(missing)
        with pytest.raises(DatasetError):
            validate_extraction(data)

    def test_gold_missing_score_points(self):
        data = _valid_extraction()
        data["gold"].pop("score_points")
        with pytest.raises(DatasetError):
            validate_extraction(data)

    def test_score_point_item_not_dict(self):
        data = _valid_extraction()
        data["gold"]["score_points"] = ["非法条目"]
        with pytest.raises(DatasetError):
            validate_extraction(data)

    def test_score_point_missing_item(self):
        data = _valid_extraction()
        data["gold"]["score_points"] = [{"clause_no": "3.2.1"}]
        with pytest.raises(DatasetError):
            validate_extraction(data)


# ── retrieval schema 校验 ──


class TestValidateRetrieval:
    def test_valid(self):
        assert validate_retrieval(_valid_retrieval()) is not None

    def test_missing_queries(self):
        data = _valid_retrieval()
        data.pop("queries")
        with pytest.raises(DatasetError):
            validate_retrieval(data)

    def test_query_missing_relevant_doc_ids(self):
        data = _valid_retrieval()
        data["queries"] = [{"query": "运维支持承诺"}]
        with pytest.raises(DatasetError):
            validate_retrieval(data)

    def test_doc_missing_chunks(self):
        data = _valid_retrieval()
        data["docs"] = [{"doc_id": "d1", "title": "运维手册"}]
        with pytest.raises(DatasetError):
            validate_retrieval(data)


# ── coverage schema 校验 ──


def _valid_coverage() -> dict:
    return {
        "id": "sample_001",
        "score_points": [{"clause_no": "3.2.1", "item": "技术方案完整性", "confirmed": True}],
        "outline": [{"chapter_no": 1, "title": "技术方案", "covered_clauses": ["3.2.1"]}],
    }


class TestValidateCoverage:
    def test_valid(self):
        assert validate_coverage(_valid_coverage()) is not None

    def test_missing_outline(self):
        data = _valid_coverage()
        data.pop("outline")
        with pytest.raises(DatasetError):
            validate_coverage(data)

    def test_score_point_missing_clause_no(self):
        data = _valid_coverage()
        data["score_points"] = [{"item": "技术方案完整性"}]
        with pytest.raises(DatasetError):
            validate_coverage(data)

    def test_outline_missing_chapter_no(self):
        data = _valid_coverage()
        data["outline"] = [{"title": "技术方案"}]
        with pytest.raises(DatasetError):
            validate_coverage(data)


# ── 目录遍历加载 ──


class TestLoadDatasetsDir:
    def test_load_sorted_and_valid(self, tmp_path):
        for name, data in [("b.json", _valid_extraction()), ("a.json", _valid_extraction())]:
            (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        datasets = load_extraction_datasets(tmp_path)
        assert [d["id"] for d in datasets] == ["sample_001", "sample_001"]

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert load_extraction_datasets(tmp_path) == []
        assert load_retrieval_datasets(tmp_path) == []

    def test_invalid_json_raises_with_filename(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(DatasetError, match=r"bad\.json"):
            load_extraction_datasets(tmp_path)

    def test_invalid_schema_raises_with_filename(self, tmp_path):
        (tmp_path / "wrong.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
        with pytest.raises(DatasetError, match=r"wrong\.json"):
            load_retrieval_datasets(tmp_path)

    def test_nonexistent_dir_raises(self, tmp_path):
        with pytest.raises(DatasetError):
            load_extraction_datasets(tmp_path / "missing")


# ── 种子样本自检（仓库内种子文件必须通过自身 schema 校验） ──


class TestSeedDatasets:
    def test_extraction_seed_valid(self):
        datasets = load_extraction_datasets(DATASETS_DIR / "extraction")
        assert len(datasets) >= 1
        assert all(d["tender_text"].strip() for d in datasets)

    def test_coverage_seed_valid(self):
        datasets = load_coverage_datasets(DATASETS_DIR / "coverage")
        assert len(datasets) >= 1
        for d in datasets:
            covered = {c for ch in d["outline"] for c in ch.get("covered_clauses") or []}
            assert covered, "种子大纲必须存在 covered_clauses"

    def test_retrieval_seed_valid(self):
        datasets = load_retrieval_datasets(DATASETS_DIR / "retrieval")
        assert len(datasets) >= 1
        for d in datasets:
            doc_ids = {doc["doc_id"] for doc in d["docs"]}
            for q in d["queries"]:
                assert set(q["relevant_doc_ids"]) <= doc_ids, "relevant 引用了不存在的 doc_id"
