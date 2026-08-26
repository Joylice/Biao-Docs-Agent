"""coverage_service 单测 — 评分点覆盖矩阵（confirmed SP vs 大纲 covered_clauses）."""

from app.services.proposal.coverage_service import compute_coverage


def _sp(clause_no: str, item: str = "评分项", confirmed: bool = True) -> dict:
    return {"clause_no": clause_no, "item": item, "confirmed": confirmed}


OUTLINE = [
    {"chapter_no": "1", "title": "概述", "covered_clauses": ["1", "2"]},
    {"chapter_no": "2", "title": "架构", "covered_clauses": ["3"]},
]


def test_full_coverage() -> None:
    """confirmed 评分点全部被大纲 covered_clauses 覆盖 → 覆盖率 1.0."""
    result = compute_coverage([_sp("1"), _sp("2"), _sp("3")], OUTLINE)
    assert result["total"] == 3
    assert result["covered"] == 3
    assert result["uncovered"] == []
    assert result["coverage_rate"] == 1.0


def test_partial_uncovered() -> None:
    """部分评分点未被任何章节覆盖 → uncovered 列出且覆盖率按比例."""
    result = compute_coverage([_sp("1"), _sp("2"), _sp("3"), _sp("4.1")], OUTLINE)
    assert result["covered"] == 3
    assert [sp["clause_no"] for sp in result["uncovered"]] == ["4.1"]
    assert result["coverage_rate"] == 0.75


def test_empty_outline() -> None:
    """空大纲 → 全部 confirmed 评分点未覆盖，覆盖率 0."""
    result = compute_coverage([_sp("1"), _sp("2")], [])
    assert result["total"] == 2
    assert result["covered"] == 0
    assert len(result["uncovered"]) == 2
    assert result["coverage_rate"] == 0.0


def test_unconfirmed_excluded() -> None:
    """未确认的评分点不参与覆盖统计."""
    result = compute_coverage([_sp("1"), _sp("9", confirmed=False)], OUTLINE)
    assert result["total"] == 1
    assert result["coverage_rate"] == 1.0


def test_no_confirmed_points() -> None:
    """无 confirmed 评分点 → 覆盖率视为 1.0（无覆盖义务）."""
    result = compute_coverage([], OUTLINE)
    assert result["total"] == 0
    assert result["coverage_rate"] == 1.0


def test_chapter_without_covered_clauses_key() -> None:
    """章节缺 covered_clauses 字段（存量大纲）→ 按未覆盖处理不报错."""
    outline = [{"chapter_no": "1", "title": "概述"}]
    result = compute_coverage([_sp("1")], outline)
    assert result["uncovered"] and result["coverage_rate"] == 0.0
