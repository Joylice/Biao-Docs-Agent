"""技术需求梳理服务测试（评分点 → 技术需求映射）."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.models.document import ScorePoint


def _sp(clause_no: str, item: str, score: float = 10.0, confirmed: bool = True) -> ScorePoint:
    return ScorePoint(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        clause_no=clause_no,
        item=item,
        score=score,
        criteria=f"{item}的评审标准",
        is_star=False,
        risk_level="mid",
        confirmed=confirmed,
    )


def _llm_result(items: list[dict]) -> dict:
    return {"requirements": items}


def _clause_key(sp: ScorePoint) -> str:
    """与提示词约定一致的评分点唯一标识（clause_no 可能重复，需叠加 item）."""
    return f"{sp.clause_no}|{sp.item}"


# ── build_requirement_rows：纯逻辑（映射回填 / source / seq 续编）──


class TestBuildRequirementRows:
    def test_matched_row_gets_sp_id_and_sp_derived_source(self) -> None:
        from app.services.requirements_service import build_requirement_rows

        sp = _sp("2.2.2(1)", "技术方案")
        rows = build_requirement_rows(
            [
                {
                    "seq": 1,
                    "description": "支持≥100并发",
                    "category": "性能",
                    "is_mandatory": True,
                    "sp_clause": _clause_key(sp),
                }
            ],
            {_clause_key(sp): sp},
            project_id=sp.project_id,
            fallback_doc_id=sp.doc_id,
            seq_start=1,
        )
        assert len(rows) == 1
        assert rows[0]["sp_id"] == sp.id
        assert rows[0]["source"] == "sp_derived"
        assert rows[0]["doc_id"] == sp.doc_id
        assert rows[0]["is_mandatory"] is True

    def test_unmatched_row_gets_null_sp_and_tender_source(self) -> None:
        from app.services.requirements_service import build_requirement_rows

        sp = _sp("2.2.2(1)", "技术方案")
        fallback_doc = uuid.uuid4()
        rows = build_requirement_rows(
            [{"seq": 1, "description": "通用需求", "sp_clause": "9.9.9"}],
            {_clause_key(sp): sp},
            project_id=sp.project_id,
            fallback_doc_id=fallback_doc,
            seq_start=1,
        )
        assert rows[0]["sp_id"] is None
        assert rows[0]["source"] == "tender"
        assert rows[0]["doc_id"] == fallback_doc

    def test_seq_continues_from_start(self) -> None:
        from app.services.requirements_service import build_requirement_rows

        sp = _sp("1.1", "项A")
        rows = build_requirement_rows(
            [
                {"seq": 1, "description": "需求一", "sp_clause": _clause_key(sp)},
                {"seq": 2, "description": "需求二", "sp_clause": _clause_key(sp)},
            ],
            {_clause_key(sp): sp},
            project_id=sp.project_id,
            fallback_doc_id=sp.doc_id,
            seq_start=6,
        )
        assert [r["seq"] for r in rows] == [6, 7]

    def test_blank_description_skipped(self) -> None:
        from app.services.requirements_service import build_requirement_rows

        sp = _sp("1.1", "项A")
        rows = build_requirement_rows(
            [{"seq": 1, "description": "  ", "sp_clause": _clause_key(sp)}],
            {_clause_key(sp): sp},
            project_id=sp.project_id,
            fallback_doc_id=sp.doc_id,
            seq_start=1,
        )
        assert rows == []

    def test_sp_clause_whitespace_normalized(self) -> None:
        from app.services.requirements_service import build_requirement_rows

        sp = _sp("4.2.1", "平台功能")
        rows = build_requirement_rows(
            [{"seq": 1, "description": "需求", "sp_clause": f" {_clause_key(sp)} "}],
            {_clause_key(sp): sp},
            project_id=sp.project_id,
            fallback_doc_id=sp.doc_id,
            seq_start=1,
        )
        assert rows[0]["sp_id"] == sp.id

    def test_duplicate_clause_no_maps_to_distinct_points(self) -> None:
        """真实招标文件同一 clause_no 下存在多个评分项，映射不得互相覆盖."""
        from app.services.requirements_service import build_requirement_rows

        sp_a = _sp("2.2.2(1)", "总体施工组织布置及规划")
        sp_b = _sp("2.2.2(1)", "承包人项目管理方案")
        clause_map = {_clause_key(sp_a): sp_a, _clause_key(sp_b): sp_b}
        rows = build_requirement_rows(
            [
                {"seq": 1, "description": "施工布置规划", "sp_clause": _clause_key(sp_a)},
                {"seq": 2, "description": "项目管理方案", "sp_clause": _clause_key(sp_b)},
            ],
            clause_map,
            project_id=sp_a.project_id,
            fallback_doc_id=sp_a.doc_id,
            seq_start=1,
        )
        assert rows[0]["sp_id"] == sp_a.id
        assert rows[1]["sp_id"] == sp_b.id


# ── generate_requirements：编排（幂等删除 / 入队写库 / 异常）──


def _result_all(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _result_scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _gen_env(monkeypatch, sps: list[ScorePoint], max_seq: int = 0, llm=None):
    """编排环境：AsyncMock 会话 + mock LLM；返回 (session, llm_mock, sps)."""
    session = AsyncMock()
    session.added = []
    session.add = MagicMock(side_effect=session.added.append)
    # execute 序列：评分点查询 → 删旧 sp_derived → max(seq)
    session.execute.side_effect = [
        _result_all(sps),
        _result_scalar(None),
        _result_scalar(max_seq),
    ]
    default_llm = (
        _llm_result(
            [
                {
                    "seq": 1,
                    "description": f"响应{sps[0].clause_no}",
                    "category": "性能",
                    "is_mandatory": True,
                    "sp_clause": _clause_key(sps[0]),
                }
            ]
        )
        if sps
        else _llm_result([])
    )
    llm_mock = AsyncMock(return_value=llm or default_llm)
    monkeypatch.setattr("app.services.llm_service.call_llm_with_schema", llm_mock)
    return session, llm_mock


@pytest.mark.asyncio
async def test_generate_uses_confirmed_points_when_ids_omitted(monkeypatch) -> None:
    from app.services import requirements_service

    sps = [_sp("2.2.2(1)", "技术方案", confirmed=True)]
    session, llm_mock = _gen_env(monkeypatch, sps)

    result = await requirements_service.generate_requirements(session, sps[0].project_id)

    assert result["total"] == 1
    assert result["mapped"] == 1
    assert result["items"][0]["related_sp"]["clause_no"] == "2.2.2(1)"
    llm_mock.assert_awaited_once()
    # 送给 LLM 的评分点载荷含 clause_no/item/criteria
    sent_user_prompt = llm_mock.call_args.kwargs.get("user_prompt") or (
        llm_mock.call_args.args[1] if len(llm_mock.call_args.args) > 1 else ""
    )
    assert "2.2.2(1)" in sent_user_prompt


@pytest.mark.asyncio
async def test_generate_idempotent_deletes_previous_sp_derived(monkeypatch) -> None:
    from app.services import requirements_service

    sps = [_sp("1.1", "项A")]
    session, _ = _gen_env(monkeypatch, sps)

    await requirements_service.generate_requirements(session, sps[0].project_id)

    deletes = [
        c.args[0]
        for c in session.execute.call_args_list
        if str(c.args[0]).lstrip().upper().startswith("DELETE")
    ]
    assert len(deletes) == 1
    assert "tech_requirements" in str(deletes[0])
    # 幂等策略：仅清理 source='sp_derived' 的旧衍生需求（字面量为绑定参数）
    assert "sp_derived" in str(deletes[0].compile().params)
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_generate_persists_rows_with_mapping(monkeypatch) -> None:
    from app.services import requirements_service

    sps = [_sp("1.1", "项A")]
    session, _ = _gen_env(monkeypatch, sps, max_seq=5)

    result = await requirements_service.generate_requirements(session, sps[0].project_id)

    assert len(session.added) == 1
    tr = session.added[0]
    assert tr.sp_id == sps[0].id
    assert tr.source == "sp_derived"
    assert tr.seq == 6, "seq 应从存量最大值续编，避免与招标原文需求冲突"
    assert result["items"][0]["seq"] == 6


@pytest.mark.asyncio
async def test_generate_no_confirmed_points_raises(monkeypatch) -> None:
    from app.services import requirements_service

    session, llm_mock = _gen_env(monkeypatch, [])

    with pytest.raises(BizError) as exc_info:
        await requirements_service.generate_requirements(session, uuid.uuid4())
    assert exc_info.value.code == 4004
    llm_mock.assert_not_awaited(), "无评分点时不得消耗 LLM 调用"


@pytest.mark.asyncio
async def test_generate_explicit_ids_missing_raises(monkeypatch) -> None:
    from app.services import requirements_service

    sps = [_sp("1.1", "项A")]
    session, llm_mock = _gen_env(monkeypatch, sps)
    unknown_id = uuid.uuid4()

    with pytest.raises(BizError) as exc_info:
        await requirements_service.generate_requirements(
            session, sps[0].project_id, score_point_ids=[sps[0].id, unknown_id]
        )
    assert exc_info.value.code == 4004
    llm_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_mock_mode_deterministic(monkeypatch) -> None:
    """mock 模式走 call_llm_with_schema 确定性降级（不 patch LLM，走真实 mock 分支）."""
    from app.services import requirements_service

    async def _mock_enabled(_mock=None):
        return True

    monkeypatch.setattr("app.services.settings_service.is_mock_enabled", _mock_enabled)

    sps = [_sp("1.1", "项A")]
    session = AsyncMock()
    session.added = []
    session.add = MagicMock(side_effect=session.added.append)
    session.execute.side_effect = [
        _result_all(sps),
        _result_scalar(None),
        _result_scalar(0),
    ]

    result = await requirements_service.generate_requirements(session, sps[0].project_id)

    # mock schema 生成 1 条 requirement（sp_clause="mock" 匹配不到 → source='tender'）
    assert result["total"] == 1
    assert result["mapped"] == 0
    assert session.added[0].source == "tender"
    assert session.added[0].sp_id is None


# ── list_requirements ──


@pytest.mark.asyncio
async def test_list_requirements_only_mapped_filters() -> None:
    from app.services import requirements_service

    session = AsyncMock()
    rows = []
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result

    items = await requirements_service.list_requirements(session, uuid.uuid4(), only_mapped=True)
    assert items == []
    stmt = str(session.execute.call_args.args[0])
    assert "sp_id IS NOT NULL" in stmt


# ── prompt loader ──


def test_load_requirements_prompt_injects_score_points_json() -> None:
    from app.services.prompt_loader import load_requirements_prompt

    system_prompt, user_prompt = load_requirements_prompt('[{"clause_no": "4.2.1"}]')
    assert system_prompt
    assert "4.2.1" in user_prompt
