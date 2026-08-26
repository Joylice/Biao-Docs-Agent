"""废标条款服务测试 — 规则比对/清洗/项目扫描（阶段 H）.

覆盖：
- normalize_severity / normalize_risk_category：非法值归一
- scan_content：仅 confirmed 条款参与；分类关键词与标题前缀命中
- scan_project_sections：章节正文命中高风险条款按章节聚合
- count_unconfirmed_high：未确认 high 条款计数
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.proposal import disqualification_service as dq


def _clause(
    *,
    severity="high",
    risk_category="qualification_missing",
    confirmed=True,
    title="资质要求",
    clause_no="2.1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        clause_no=clause_no,
        title=title,
        risk_category=risk_category,
        severity=severity,
        recommendation="请核查资质证书",
        confirmed=confirmed,
    )


class TestNormalize:
    def test_severity_valid_lowercase(self) -> None:
        assert dq.normalize_severity("HIGH") == "high"
        assert dq.normalize_severity("mid") == "mid"
        assert dq.normalize_severity("low") == "low"

    def test_severity_invalid_defaults_mid(self) -> None:
        assert dq.normalize_severity("mock") == "mid"
        assert dq.normalize_severity(None) == "mid"
        assert dq.normalize_severity("") == "mid"

    def test_risk_category_known_passthrough(self) -> None:
        assert dq.normalize_risk_category("blind_bid") == "blind_bid"

    def test_risk_category_unknown_defaults_other(self) -> None:
        assert dq.normalize_risk_category("mock") == "other"
        assert dq.normalize_risk_category(None) == "other"


class TestScanContent:
    def test_high_confirmed_category_keyword_hit(self) -> None:
        hits = dq.scan_content("我方具备建筑业企业资质与安全生产许可证", [_clause()])
        assert len(hits) == 1
        assert hits[0]["clause_no"] == "2.1"
        assert hits[0]["severity"] == "high"
        assert "资质" in hits[0]["matched"]

    def test_unconfirmed_clause_skipped(self) -> None:
        hits = dq.scan_content("我方具备建筑业企业资质", [_clause(confirmed=False)])
        assert hits == []

    def test_title_prefix_hit(self) -> None:
        clause = _clause(risk_category="other", title="投标保证金缴纳凭证")
        hits = dq.scan_content("本章说明投标保证金缴纳凭证的提交方式", [clause])
        assert len(hits) == 1

    def test_no_keyword_no_hit(self) -> None:
        hits = dq.scan_content("本章描述总体施工部署与平面布置", [_clause()])
        assert hits == []


class TestScanProjectSections:
    @pytest.mark.asyncio
    async def test_aggregates_hits_by_chapter(self) -> None:
        clause = _clause()
        section = SimpleNamespace(section_id="ch03", title="资质章节", content_md="我方资质齐全")
        db = AsyncMock()
        db.execute.side_effect = [
            MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[clause])))
            ),
            MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[section])))
            ),
        ]
        risks = await dq.scan_project_sections(db, uuid.uuid4())
        assert "ch03" in risks
        assert risks["ch03"][0]["clause_no"] == "2.1"

    @pytest.mark.asyncio
    async def test_no_clauses_returns_empty(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        risks = await dq.scan_project_sections(db, uuid.uuid4())
        assert risks == {}


class TestCountUnconfirmedHigh:
    @pytest.mark.asyncio
    async def test_returns_scalar_count(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 2
        db.execute.return_value = result
        assert await dq.count_unconfirmed_high(db, uuid.uuid4()) == 2


class TestCheckChapterContent:
    @pytest.mark.asyncio
    async def test_uses_own_session_and_scans(self) -> None:
        clause = _clause()
        session = AsyncMock()
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[clause])))
        )
        with patch.object(dq, "async_session_factory", MagicMock(return_value=_ctx(session))):
            hits = await dq.check_chapter_content(str(uuid.uuid4()), "我方资质齐全")
        assert len(hits) == 1


def _ctx(session):
    class _CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return _CM()
