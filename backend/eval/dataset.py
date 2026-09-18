"""评测数据集 schema 校验与目录加载（字段口径对齐 ParsedTender 提取结果）。

extraction 数据集：{id, name, tender_text, gold: {score_points, [disqualification_clauses,
                   format_requirements, glossary]}}
coverage 数据集：{id, score_points, outline}（格式同工作流 state）
retrieval 数据集：{id, docs: [{doc_id, title, chunks}], queries: [{query, relevant_doc_ids}]}
真实标注样本由业务人员按此 schema 追加到 eval/datasets/ 对应子目录。

gold 口径与生产 `app.services.document.parsing.results.ParsedTender` 对齐：
`score_points` 为必需（extraction 任务唯一评分对象），其余为可选补充标注，存在时按其
生产结构校验。P3（2026-09）已全链路移除 `tech_requirements` 概念，本模块**显式拒绝**
该字段，防止评测口径与生产脱节后静默回退（见 docs/dev-plan-remediation.md T0.1）。
"""

from __future__ import annotations

import json
from pathlib import Path


class DatasetError(Exception):
    """数据集文件不存在 / JSON 损坏 / schema 不合法."""


# 已废弃的 gold 字段 → 替代建议（报错时给出可执行指引）
_DEPRECATED_GOLD_FIELDS: dict[str, str] = {
    "tech_requirements": (
        "技术需求已于 P3 全链路移除，不再标注；如需标注废标/红线条款请改用 disqualification_clauses"
    ),
}

# 可选补充标注：字段名 → 条目的必需键（对齐 ParsedTender 生产结构）
_OPTIONAL_GOLD_SECTIONS: dict[str, str] = {
    "disqualification_clauses": "clause_no",
    "format_requirements": "category",
    "glossary": "term",
}


def validate_extraction(data: dict) -> dict:
    """校验评分点提取评测集，非法抛 DatasetError."""
    for key in ("id", "name", "tender_text", "gold"):
        if key not in data:
            raise DatasetError(f"缺少顶层字段: {key}")
    gold = data["gold"]
    if not isinstance(gold, dict) or "score_points" not in gold:
        raise DatasetError("gold 必须包含 score_points")
    for field_name, hint in _DEPRECATED_GOLD_FIELDS.items():
        if field_name in gold:
            raise DatasetError(f"gold 含已废弃字段 {field_name}：{hint}")
    for sp in gold["score_points"]:
        if not isinstance(sp, dict) or "item" not in sp:
            raise DatasetError("score_points 条目必须为含 item 的对象")
    for section, required_key in _OPTIONAL_GOLD_SECTIONS.items():
        for entry in gold.get(section) or []:
            if not isinstance(entry, dict) or required_key not in entry:
                raise DatasetError(f"{section} 条目必须为含 {required_key} 的对象")
    return data


def validate_coverage(data: dict) -> dict:
    """校验方案覆盖评测集（score_points + outline），非法抛 DatasetError."""
    for key in ("id", "score_points", "outline"):
        if key not in data:
            raise DatasetError(f"缺少顶层字段: {key}")
    for sp in data["score_points"]:
        if not isinstance(sp, dict) or "clause_no" not in sp or "item" not in sp:
            raise DatasetError("score_points 条目必须为含 clause_no/item 的对象")
    for ch in data["outline"]:
        if not isinstance(ch, dict) or "chapter_no" not in ch or "title" not in ch:
            raise DatasetError("outline 条目必须为含 chapter_no/title 的对象")
    return data


def validate_retrieval(data: dict) -> dict:
    """校验检索评测集，非法抛 DatasetError."""
    for key in ("id", "docs", "queries"):
        if key not in data:
            raise DatasetError(f"缺少顶层字段: {key}")
    for doc in data["docs"]:
        if not isinstance(doc, dict) or "doc_id" not in doc or "chunks" not in doc:
            raise DatasetError("docs 条目必须为含 doc_id/chunks 的对象")
    for q in data["queries"]:
        if not isinstance(q, dict) or "query" not in q or "relevant_doc_ids" not in q:
            raise DatasetError("queries 条目必须为含 query/relevant_doc_ids 的对象")
    return data


def _load_dir(dataset_dir: Path, validator) -> list[dict]:
    """按文件名排序加载目录下全部 *.json 并校验."""
    if not dataset_dir.is_dir():
        raise DatasetError(f"数据集目录不存在: {dataset_dir}")
    datasets: list[dict] = []
    for path in sorted(dataset_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatasetError(f"JSON 解析失败: {path.name} ({exc})") from exc
        try:
            datasets.append(validator(data))
        except DatasetError as exc:
            raise DatasetError(f"schema 校验失败: {path.name} ({exc})") from exc
    return datasets


def load_extraction_datasets(dataset_dir: Path) -> list[dict]:
    return _load_dir(Path(dataset_dir), validate_extraction)


def load_coverage_datasets(dataset_dir: Path) -> list[dict]:
    return _load_dir(Path(dataset_dir), validate_coverage)


def load_retrieval_datasets(dataset_dir: Path) -> list[dict]:
    return _load_dir(Path(dataset_dir), validate_retrieval)
