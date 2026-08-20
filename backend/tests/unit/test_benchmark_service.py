"""评分对标服务单测 — 阶段 D（SDD §3.4：风险分级算法 + coverage + 排序）."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.document import ScorePoint
from app.services import benchmark_service

PROJECT_ID = uuid.uuid4()


def _sp(clause_no: str, item: str, score: float, criteria: str = "", strategy=None) -> ScorePoint:
    return ScorePoint(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        doc_id=uuid.uuid4(),
        clause_no=clause_no,
        item=item,
        score=score,
        criteria=criteria,
        is_star=False,
        strategy=strategy,
        risk_level=None,
        confirmed=True,
    )


class TestRiskLevel:
    """risk = f(score, coverage)：阈值边界."""

    def test_high_when_high_score_and_low_coverage(self) -> None:
        assert benchmark_service.risk_level(6.0, 0.0) == "high"
        assert benchmark_service.risk_level(8.0, 0.29) == "high"

    def test_not_high_at_coverage_boundary(self) -> None:
        # coverage == 0.3 不满足 < 0.3 → 落入 mid（score ≥ 3）
        assert benchmark_service.risk_level(8.0, 0.3) == "mid"

    def test_mid_when_score_ge_3(self) -> None:
        assert benchmark_service.risk_level(3.0, 0.9) == "mid"

    def test_mid_when_low_coverage(self) -> None:
        assert benchmark_service.risk_level(2.0, 0.5) == "mid"

    def test_low_when_low_score_and_high_coverage(self) -> None:
        assert benchmark_service.risk_level(2.0, 0.6) == "low"
        assert benchmark_service.risk_level(0.0, 1.0) == "low"


class TestComputeItemCoverage:
    @pytest.mark.asyncio
    async def test_mock_mode_deterministic(self) -> None:
        """mock 模式确定性规则：同输入同输出，值域 [0,1]."""
        sp = _sp("1.1", "技术方案完整性", 6.0, "方案完整可行")
        db = AsyncMock()
        with patch.object(
            benchmark_service.settings_service, "is_mock_enabled", AsyncMock(return_value=True)
        ):
            c1 = await benchmark_service.compute_item_coverage(db, PROJECT_ID, sp)
            c2 = await benchmark_service.compute_item_coverage(db, PROJECT_ID, sp)
        assert c1 == c2
        assert 0.0 <= c1 <= 1.0

    @pytest.mark.asyncio
    async def test_real_mode_hits_over_top_k(self) -> None:
        """真实模式：coverage = 检索命中数 / top_k."""
        sp = _sp("1.2", "安全保障", 4.0, "等保三级")
        db = AsyncMock()
        hits = [MagicMock(), MagicMock(), MagicMock()]
        with (
            patch.object(
                benchmark_service.settings_service,
                "is_mock_enabled",
                AsyncMock(return_value=False),
            ),
            patch.object(benchmark_service, "_retrieve", AsyncMock(return_value=hits)),
        ):
            coverage = await benchmark_service.compute_item_coverage(db, PROJECT_ID, sp)
        assert coverage == pytest.approx(3 / benchmark_service.COVERAGE_TOP_K)

    @pytest.mark.asyncio
    async def test_empty_query_zero(self) -> None:
        sp = _sp("1.3", "", 1.0, "")
        db = AsyncMock()
        with patch.object(
            benchmark_service.settings_service, "is_mock_enabled", AsyncMock(return_value=True)
        ):
            assert await benchmark_service.compute_item_coverage(db, PROJECT_ID, sp) == 0.0


class TestBuildBenchmark:
    @pytest.mark.asyncio
    async def test_sorted_by_score_times_gap_desc_and_risk_writeback(self) -> None:
        """排序键 score × (1 - coverage) 降序；risk_level 懒回写."""
        # coverage 固定 0.2（mock patch）→ 排序等价于 score 降序
        sps = [
            _sp("2", "低分项", 2.0),
            _sp("1", "高分项", 8.0),
            _sp("3", "中分项", 4.0),
        ]
        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = sps
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)

        with patch.object(
            benchmark_service, "compute_item_coverage", AsyncMock(return_value=0.2)
        ):
            items = await benchmark_service.build_benchmark(db, PROJECT_ID)

        assert [i["clause_no"] for i in items] == ["1", "3", "2"]
        # score × (1 - coverage)：8×0.8=6.4 > 4×0.8=3.2 > 2×0.8=1.6
        assert items[0]["risk"] == "high"  # score=8 ≥6 且 coverage=0.2 <0.3
        assert all(sp.risk_level is not None for sp in sps)
        assert set(items[0].keys()) >= {
            "clause_no", "item", "score", "criteria", "strategy", "risk", "coverage",
        }

    @pytest.mark.asyncio
    async def test_coverage_zero_high_risk(self) -> None:
        """资料库无素材（coverage=0）+ 高分 → high（提示售前补资料）."""
        sp = _sp("1", "重点项", 6.0)
        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [sp]
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)

        with patch.object(
            benchmark_service, "compute_item_coverage", AsyncMock(return_value=0.0)
        ):
            items = await benchmark_service.build_benchmark(db, PROJECT_ID)
        assert items[0]["risk"] == "high"
        assert sp.risk_level == "high"


class TestLoadHighRiskPoints:
    """write_node 注入用高风险评分点加载（1.4 对标注入生成）."""

    def _db_with(self, sps: list) -> AsyncMock:
        db = AsyncMock()
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = sps
        result.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result)
        return db

    @pytest.mark.asyncio
    async def test_returns_strategy_fallback_item(self) -> None:
        """strategy 缺失时回退 item 作为要点."""
        sp1 = _sp("1", "高分项", 8.0, strategy="补充案例")
        sp2 = _sp("2", "无策略项", 7.0)
        db = self._db_with([sp1, sp2])
        with patch.object(
            benchmark_service.settings_service, "is_mock_enabled", AsyncMock(return_value=False)
        ):
            points = await benchmark_service.load_high_risk_points(db, PROJECT_ID)
        assert points == [
            {"clause_no": "1", "strategy": "补充案例"},
            {"clause_no": "2", "strategy": "无策略项"},
        ]

    @pytest.mark.asyncio
    async def test_mock_mode_injects_deterministic_sample_when_empty(self) -> None:
        """mock 模式无高风险记录 → 注入确定性样本（回归验证用）."""
        db = self._db_with([])
        with patch.object(
            benchmark_service.settings_service, "is_mock_enabled", AsyncMock(return_value=True)
        ):
            points = await benchmark_service.load_high_risk_points(db, PROJECT_ID)
        assert points == benchmark_service.MOCK_HIGH_RISK_SAMPLE

    @pytest.mark.asyncio
    async def test_real_mode_empty_stays_empty(self) -> None:
        db = self._db_with([])
        with patch.object(
            benchmark_service.settings_service, "is_mock_enabled", AsyncMock(return_value=False)
        ):
            assert await benchmark_service.load_high_risk_points(db, PROJECT_ID) == []
