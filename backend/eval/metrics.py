"""评测框架离线度量函数（纯计算，无 IO/LLM）。

指标口径（对齐 SDD §10.2 验收标准）：
- 评分点匹配：clause_no 精确匹配优先；clause_no 缺失时按 item 字符 bigram F1 兜底；
  每条 gold 最多被命中一次（重复预测只计一次 TP，其余计 FP）；
- precision/recall/F1：空 gold + 空预测视为满分；空 gold 有预测 → precision=0；
  空预测有 gold → recall=0；
- 检索指标：Recall@k 与 MRR，relevant 为空集时 Recall@k 记 1.0（无可检索目标）。
"""

from __future__ import annotations

from collections import Counter


def _bigrams(text: str) -> list[str]:
    return [text[i : i + 2] for i in range(len(text) - 1)]


def char_bigram_f1(a: str, b: str) -> float:
    """字符 bigram 多重集 F1（中文短文本相似度兜底度量）。"""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ca, cb = Counter(_bigrams(a)), Counter(_bigrams(b))
    common = sum((ca & cb).values())
    if common == 0:
        return 0.0
    precision = common / sum(ca.values())
    recall = common / sum(cb.values())
    return 2 * precision * recall / (precision + recall)


def match_score_points(
    gold: list[dict],
    preds: list[dict],
    item_threshold: float = 0.5,
) -> dict[str, int]:
    """评分点匹配计数：返回 {"tp", "fp", "fn"}。

    - clause_no 非空时精确匹配（strip 后比较），优先于模糊匹配；
    - clause_no 为空时按 item bigram F1 ≥ item_threshold 命中未匹配 gold；
    - 每条 gold 最多命中一次。
    """
    matched_gold: set[int] = set()

    def _norm_clause(v: str | None) -> str:
        return (v or "").strip()

    for pred in preds:
        pred_clause = _norm_clause(pred.get("clause_no"))
        hit_idx = None
        if pred_clause:
            for gi, g in enumerate(gold):
                if gi not in matched_gold and _norm_clause(g.get("clause_no")) == pred_clause:
                    hit_idx = gi
                    break
        if hit_idx is None:
            pred_item = (pred.get("item") or "").strip()
            best_score, best_idx = 0.0, None
            for gi, g in enumerate(gold):
                if gi in matched_gold:
                    continue
                score = char_bigram_f1(pred_item, (g.get("item") or "").strip())
                if score > best_score:
                    best_score, best_idx = score, gi
            if best_score >= item_threshold and best_idx is not None:
                hit_idx = best_idx
        if hit_idx is not None:
            matched_gold.add(hit_idx)

    tp = len(matched_gold)
    return {
        "tp": tp,
        "fp": len(preds) - tp,
        "fn": len(gold) - tp,
    }


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    """由 TP/FP/FN 计算 precision/recall/F1（边界口径见模块 docstring）。"""
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def retrieval_recall_at_k(
    ranked_doc_ids: list[str],
    relevant_doc_ids: set[str],
    k: int = 8,
) -> float:
    """前 k 个检索结果命中的 relevant 占比；relevant 为空记 1.0。"""
    if not relevant_doc_ids:
        return 1.0
    if not ranked_doc_ids:
        return 0.0
    top_k = ranked_doc_ids[:k]
    return len(set(top_k) & relevant_doc_ids) / len(relevant_doc_ids)


def retrieval_mrr(ranked_doc_ids: list[str], relevant_doc_ids: set[str]) -> float:
    """首个命中的倒数排名（MRR）；无命中或无 relevant 记 0.0。"""
    if not relevant_doc_ids or not ranked_doc_ids:
        return 0.0
    for i, doc_id in enumerate(ranked_doc_ids, start=1):
        if doc_id in relevant_doc_ids:
            return 1.0 / i
    return 0.0


def evaluate_thresholds(
    metrics: dict[str, float],
    thresholds: dict[str, float],
) -> dict[str, bool]:
    """逐项达标判定：指标缺失视为未达标。"""
    return {name: metrics.get(name, float("-inf")) >= bar for name, bar in thresholds.items()}
