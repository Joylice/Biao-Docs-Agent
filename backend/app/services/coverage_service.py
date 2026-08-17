"""评分点覆盖矩阵服务 — confirmed 评分点 vs 大纲 covered_clauses.

生成前计算覆盖率：未覆盖的 confirmed 评分点由调用方注入章节提示词补写，
覆盖率随 progress 事件推送前端展示（对齐 SDD 验收「方案评分点覆盖 ≥ 90%」）。
"""


def compute_coverage(score_points: list[dict], outline: list[dict]) -> dict:
    """计算已确认评分点的大纲覆盖率.

    返回 {total, covered, uncovered: [sp], coverage_rate}；
    无 confirmed 评分点时覆盖率视为 1.0（无覆盖义务）。
    """
    confirmed = [sp for sp in score_points if sp.get("confirmed", True)]
    covered_clauses: set[str] = set()
    for chapter in outline:
        for clause in chapter.get("covered_clauses") or []:
            covered_clauses.add(str(clause))

    uncovered = [sp for sp in confirmed if str(sp.get("clause_no", "")) not in covered_clauses]
    total = len(confirmed)
    rate = 1.0 if total == 0 else round((total - len(uncovered)) / total, 4)
    return {
        "total": total,
        "covered": total - len(uncovered),
        "uncovered": uncovered,
        "coverage_rate": rate,
    }
