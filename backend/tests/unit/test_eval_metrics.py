"""阶段一 TDD 红：eval/metrics.py 度量函数（评分点匹配/准召率/检索指标/达标判定）."""

import pytest

from eval.metrics import (
    char_bigram_f1,
    evaluate_thresholds,
    match_score_points,
    precision_recall_f1,
    retrieval_mrr,
    retrieval_recall_at_k,
)

# ── 字符 bigram F1（clause_no 缺失时的 item 兜底匹配） ──


class TestCharBigramF1:
    def test_identical_strings_full_score(self):
        assert char_bigram_f1("提供7×24小时运维支持", "提供7×24小时运维支持") == 1.0

    def test_disjoint_strings_zero(self):
        assert char_bigram_f1("甲乙丙丁", "子丑寅卯") == 0.0

    def test_partial_overlap_between(self):
        score = char_bigram_f1("提供运维支持服务", "提供运维保障服务")
        assert 0.0 < score < 1.0

    def test_empty_string_zero(self):
        assert char_bigram_f1("", "任意内容") == 0.0
        assert char_bigram_f1("任意内容", "") == 0.0
        assert char_bigram_f1("", "") == 0.0

    def test_single_char_no_bigram_zero(self):
        # 单字符无 bigram，无法匹配
        assert char_bigram_f1("甲", "甲") == 0.0


# ── 评分点匹配（clause_no 精确优先，item F1 兜底，重复预测只计一次） ──


class TestMatchScorePoints:
    def _sp(self, clause_no, item):
        return {"clause_no": clause_no, "item": item}

    def test_exact_clause_no_match(self):
        gold = [self._sp("3.2.1", "技术方案完整性")]
        preds = [self._sp("3.2.1", "措辞不同的表述")]
        result = match_score_points(gold, preds)
        assert result["tp"] == 1 and result["fp"] == 0 and result["fn"] == 0

    def test_item_f1_fallback_when_clause_no_missing(self):
        gold = [self._sp("", "提供7×24小时运维支持服务")]
        preds = [self._sp("", "提供7×24小时运维支持")]
        result = match_score_points(gold, preds, item_threshold=0.5)
        assert result["tp"] == 1

    def test_item_f1_below_threshold_not_matched(self):
        gold = [self._sp("", "技术方案完整性")]
        preds = [self._sp("", "项目团队人员资质")]
        result = match_score_points(gold, preds, item_threshold=0.5)
        assert result["tp"] == 0
        assert result["fp"] == 1 and result["fn"] == 1

    def test_duplicate_prediction_counts_once(self):
        gold = [self._sp("3.2.1", "技术方案完整性")]
        preds = [
            self._sp("3.2.1", "技术方案完整性"),
            self._sp("3.2.1", "技术方案完整性"),
        ]
        result = match_score_points(gold, preds)
        assert result["tp"] == 1 and result["fp"] == 1 and result["fn"] == 0

    def test_clause_no_preferred_over_fuzzy(self):
        gold = [self._sp("3.2.1", "A"), self._sp("", "提供7×24小时运维支持服务")]
        preds = [self._sp("3.2.1", "提供7×24小时运维支持服务")]
        result = match_score_points(gold, preds)
        # 应命中 clause_no=3.2.1 的 gold，而非模糊命中第二条
        assert result["tp"] == 1
        assert result["fn"] == 1  # 第二条 gold 未被命中


# ── 准召率计算 ──


class TestPrecisionRecallF1:
    def test_all_hit(self):
        m = precision_recall_f1(tp=5, fp=0, fn=0)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0

    def test_partial(self):
        m = precision_recall_f1(tp=3, fp=1, fn=2)
        assert m["precision"] == pytest.approx(0.75)
        assert m["recall"] == pytest.approx(0.6)
        assert m["f1"] == pytest.approx(2 * 0.75 * 0.6 / 1.35)

    def test_empty_gold_and_preds_perfect(self):
        m = precision_recall_f1(tp=0, fp=0, fn=0)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0

    def test_empty_gold_with_preds_zero_precision(self):
        m = precision_recall_f1(tp=0, fp=2, fn=0)
        assert m["precision"] == 0.0
        assert m["recall"] == 1.0
        assert m["f1"] == 0.0

    def test_empty_preds_with_gold_zero_recall(self):
        m = precision_recall_f1(tp=0, fp=0, fn=3)
        assert m["precision"] == 1.0
        assert m["recall"] == 0.0
        assert m["f1"] == 0.0


# ── 检索指标 ──


class TestRetrievalMetrics:
    def test_recall_at_k(self):
        ranked = ["d1", "d2", "d3"]
        assert retrieval_recall_at_k(ranked, {"d1", "d3"}, k=8) == 1.0
        assert retrieval_recall_at_k(ranked, {"d1", "d9"}, k=8) == 0.5
        assert retrieval_recall_at_k(ranked, {"d9"}, k=8) == 0.0

    def test_recall_truncates_at_k(self):
        ranked = [f"d{i}" for i in range(10)]
        assert retrieval_recall_at_k(ranked, {"d9"}, k=8) == 0.0

    def test_recall_empty_relevant_is_perfect(self):
        assert retrieval_recall_at_k(["d1"], set(), k=8) == 1.0

    def test_recall_empty_ranked_zero(self):
        assert retrieval_recall_at_k([], {"d1"}, k=8) == 0.0

    def test_mrr_first_hit_position(self):
        assert retrieval_mrr(["d1", "d2"], {"d1"}) == 1.0
        assert retrieval_mrr(["d1", "d2"], {"d2"}) == 0.5
        assert retrieval_mrr(["d1", "d2"], {"d9"}) == 0.0

    def test_mrr_empty_inputs(self):
        assert retrieval_mrr([], {"d1"}) == 0.0
        assert retrieval_mrr(["d1"], set()) == 0.0


# ── 达标判定 ──


class TestEvaluateThresholds:
    def test_pass_fail_mix(self):
        metrics = {"f1": 0.9, "coverage_rate": 0.8}
        thresholds = {"f1": 0.85, "coverage_rate": 0.9}
        verdict = evaluate_thresholds(metrics, thresholds)
        assert verdict == {"f1": True, "coverage_rate": False}

    def test_exact_boundary_passes(self):
        assert evaluate_thresholds({"f1": 0.85}, {"f1": 0.85}) == {"f1": True}

    def test_metric_absent_fails(self):
        assert evaluate_thresholds({}, {"f1": 0.85}) == {"f1": False}
