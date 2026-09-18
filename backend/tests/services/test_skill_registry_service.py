"""Skill 注册表 + 服务层单测 — 双源合并 / 覆盖规则 / 门禁.

用 FakeDB 模拟 AsyncSession（对齐 tests/agents/test_graph.py 的既有做法），
避免引入 PostgreSQL 依赖，保证本机可跑。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.user_skill import UserSkill
from app.services.skills import registry, service
from app.services.skills.contract import SKILL_BODY_MAX_CHARS, parse_skill_md
from app.services.skills.loader import invalidate as invalidate_builtin

# ── FakeDB ──


class _Scalars:
    """模拟 `Result.scalars()` 返回的 ScalarResult."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Result:
    """模拟 SQLAlchemy 2.x 的 `Result`（只有 execute() 的返回值，不能是 ScalarResult 本身）."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeDB:
    """最小 AsyncSession 替身：支持 execute/select 过滤、add/delete/flush.

    只理解本模块被测代码实际发出的两种 select：

    - ``where(UserSkill.enabled.is_(True))`` → 过滤 `enabled`（无绑定参数）
    - ``where(UserSkill.name == <name>)`` → 按 name 过滤（绑定参数在 compiled.params 里）
    - ``order_by(UserSkill.name)``（无 where）→ 全量（含 disabled）

    实现**不读 SQLAlchemy 私有属性**：用 `len(stmt._where_criteria)` 判「有无过滤」
    （实测：无条件全量查询该值为 0，且编译 SQL 里连 `WHERE` 都不出现），
    再用 `stmt.compile().params` 的取值判是哪种过滤（实测 name 过滤得 `{'name_1': 'x'}`，
    enabled 过滤得 `{}` —— 因 `IS true` 是字面量不是绑定参数）。
    """

    def __init__(self, rows: list[UserSkill] | None = None) -> None:
        self.rows: list[UserSkill] = list(rows or [])
        self.deleted: list[UserSkill] = []
        self.flush_count = 0

    async def execute(self, stmt: Any) -> _Result:
        rows = self.rows
        name_filter = _bind_param_value(stmt, "name")
        if name_filter is not None:
            rows = [r for r in rows if r.name == name_filter]
        elif _has_where(stmt):
            # 有 where 但无 name 绑定参数 ⇒ 唯一可能是 enabled.is_(True)
            rows = [r for r in rows if r.enabled]
        return _Result(rows)

    def add(self, obj: UserSkill) -> None:
        self.rows.append(obj)

    async def delete(self, obj: UserSkill) -> None:
        self.deleted.append(obj)
        if obj in self.rows:
            self.rows.remove(obj)

    async def flush(self) -> None:
        self.flush_count += 1


def _has_where(stmt: Any) -> bool:
    """语句是否带 WHERE（用编译产物判断，不读私有属性版式）.

    实测坑：编译文本里 `FROM user_skills` 后**带一个尾随空格**再接换行
    （`FROM user_skills \\nWHERE ...`），故不能用 `" WHERE "` 直接匹配
    —— 必须先把空白折叠再判。无条件查询（全量 list）编译产物里不出现 WHERE。
    """
    flat = " ".join(str(stmt.compile()).split())
    return " WHERE " in flat


def _bind_param_value(stmt: Any, prefix: str) -> str | None:
    """从编译参数里取以 `prefix_` 开头的绑定值（SQLAlchemy 命名如 `name_1`）."""
    try:
        params = stmt.compile().params
    except Exception:  # pragma: no cover - 仅在非法语句下发生
        return None
    for key, value in params.items():
        if key == prefix or key.startswith(f"{prefix}_"):
            return str(value)
    return None


def _row(name: str, **kw: Any) -> UserSkill:
    row = UserSkill(
        name=name,
        title=kw.get("title", "标题"),
        description=kw.get("description", "描述"),
        skill_version=kw.get("skill_version", "1.0.0"),
        stage_key=kw.get("stage_key", "parse"),
        agent_id=kw.get("agent_id"),
        body_md=kw.get("body_md", "行为准则正文"),
        metadata_json=kw.get("metadata_json", {}),
        enabled=kw.get("enabled", True),
        created_by=kw.get("created_by", "user"),
        version=kw.get("version", 1),
    )
    row.id = kw.get("id", uuid.uuid4())
    return row


@pytest.fixture(autouse=True)
def _clear_caches() -> Any:
    invalidate_builtin()
    registry.invalidate()
    yield
    invalidate_builtin()
    registry.invalidate()


# ── registry: 双源合并 ──


class TestListSkills:
    async def test_without_db_returns_builtin_only(self) -> None:
        skills = await registry.list_skills()
        names = {c.name for c in skills}
        assert "parse_score" in names
        assert all(c.builtin for c in skills)

    async def test_merges_user_layer(self) -> None:
        db = FakeDB([_row("my_custom", stage_key="parse")])
        skills = await registry.list_skills(db)  # type: ignore[arg-type]
        by_name = {c.name: c for c in skills}
        assert "my_custom" in by_name
        assert by_name["my_custom"].builtin is False
        assert "parse_score" in by_name  # 内置层仍在

    async def test_user_layer_shadows_builtin_same_name(self) -> None:
        """同名时用户层覆盖内置层（本表的 enabled 行优先）."""
        db = FakeDB([_row("parse_score", body_md="用户覆盖版", agent_id="score_agent")])
        skills = await registry.list_skills(db)  # type: ignore[arg-type]
        hit = next(c for c in skills if c.name == "parse_score")
        assert hit.builtin is False
        assert hit.body == "用户覆盖版"
        # 不出现重复条目
        assert sum(1 for c in skills if c.name == "parse_score") == 1

    async def test_disabled_user_skill_falls_back_to_builtin(self) -> None:
        """enabled=False ⇒ 视为不存在 ⇒ 回退内置（LLM 自建待人审的核心机制）."""
        db = FakeDB([_row("parse_score", body_md="待审覆盖", enabled=False)])
        skills = await registry.list_skills(db)  # type: ignore[arg-type]
        hit = next(c for c in skills if c.name == "parse_score")
        assert hit.builtin is True
        assert hit.body != "待审覆盖"

    async def test_sorted_by_name(self) -> None:
        db = FakeDB([_row("zzz_skill"), _row("aaa_skill")])
        skills = await registry.list_skills(db)  # type: ignore[arg-type]
        names = [c.name for c in skills]
        assert names == sorted(names)

    async def test_owner_id_does_not_filter(self) -> None:
        """产品口径②B：用户层全员共享 ⇒ owner_id 不影响可见性."""
        db = FakeDB([_row("shared_skill")])
        a = await registry.list_skills(db, owner_id=uuid.uuid4())  # type: ignore[arg-type]
        registry.invalidate()
        b = await registry.list_skills(db, owner_id=uuid.uuid4())  # type: ignore[arg-type]
        assert {c.name for c in a} == {c.name for c in b}

    async def test_invalid_user_row_skipped(self) -> None:
        """name 非法的存量行被跳过，不阻断整体（降级不阻断）."""
        db = FakeDB([_row("Bad-Name!"), _row("good_skill")])
        skills = await registry.list_skills(db)  # type: ignore[arg-type]
        names = {c.name for c in skills}
        assert "good_skill" in names
        assert "Bad-Name!" not in names


class TestFindSkill:
    async def test_user_layer_priority(self) -> None:
        db = FakeDB([_row("parse_score", body_md="用户版")])
        hit = await registry.find_skill("parse_score", db)  # type: ignore[arg-type]
        assert hit is not None and hit.body == "用户版"

    async def test_falls_back_to_builtin(self) -> None:
        db = FakeDB([])
        hit = await registry.find_skill("parse_score", db)  # type: ignore[arg-type]
        assert hit is not None and hit.builtin is True

    async def test_missing_returns_none(self) -> None:
        assert await registry.find_skill("no_such_skill", FakeDB([])) is None  # type: ignore[arg-type]


class TestFindSkillForAgent:
    async def test_resolves_builtin_agent_skill(self) -> None:
        hit = await registry.find_skill_for_agent("score_agent", "parse", FakeDB([]))  # type: ignore[arg-type]
        assert hit is not None and hit.name == "parse_score"

    async def test_user_override_wins(self) -> None:
        """用户层同 (agent_id, stage_key) 且 name 与内置**不同**时也参与竞争.

        刻意与「同名覆盖」解耦：这里只验证用户层 skill 能被 agent 解析到
        （同名覆盖规则由 `test_user_layer_shadows_builtin_same_name` 单独覆盖）。
        """
        db = FakeDB(
            [
                _row(
                    "my_score",
                    agent_id="score_agent",
                    stage_key="parse",
                    skill_version="9.9.9",
                )
            ]
        )
        hit = await registry.find_skill_for_agent("score_agent", "parse", db)  # type: ignore[arg-type]
        assert hit is not None
        # 用户层 version 9.9.9 > 内置 parse_score 的 1.0.0 ⇒ 必须取用户层
        assert hit.name == "my_score"
        assert hit.builtin is False

    async def test_higher_version_wins_among_same_agent(self) -> None:
        """同 (agent_id, stage_key) 多命中 ⇒ 按 version 取最高（确定性断言）."""
        db = FakeDB(
            [
                _row("low_ver", agent_id="score_agent", stage_key="parse", skill_version="1.0.0"),
                _row("high_ver", agent_id="score_agent", stage_key="parse", skill_version="9.9.9"),
            ]
        )
        hit = await registry.find_skill_for_agent("score_agent", "parse", db)  # type: ignore[arg-type]
        assert hit is not None
        # 内置 parse_score version="1.0.0" 也参与竞争，但 9.9.9 最高 ⇒ 必为 high_ver
        assert hit.name == "high_ver"

    async def test_unknown_agent_returns_none(self) -> None:
        assert await registry.find_skill_for_agent("nobody", "parse", FakeDB([])) is None  # type: ignore[arg-type]


# ── service: 门禁 ──


class TestCreateSkillGates:
    @pytest.mark.parametrize("bad", ["Bad-Name", "..", "a", "has space", "UPPER", "9start"])
    async def test_rejects_bad_name(self, bad: str) -> None:
        with pytest.raises(ValidationError, match=r"名称|非法"):
            await service.create_skill(
                FakeDB(),  # type: ignore[arg-type]
                name=bad,
                title="T",
                description="D",
                stage_key="parse",
                body_md="正文",
            )

    async def test_rejects_builtin_shadow(self) -> None:
        """不得覆盖内置准则 —— 防用户改坏系统行为."""
        with pytest.raises(ConflictError, match="与内置准则同名"):
            await service.create_skill(
                FakeDB(),  # type: ignore[arg-type]
                name="parse_score",
                title="T",
                description="D",
                stage_key="parse",
                body_md="正文",
            )

    async def test_rejects_duplicate_user_skill(self) -> None:
        db = FakeDB([_row("dup_skill")])
        with pytest.raises(ConflictError, match="已存在"):
            await service.create_skill(
                db,  # type: ignore[arg-type]
                name="dup_skill",
                title="T",
                description="D",
                stage_key="parse",
                body_md="正文",
            )

    async def test_rejects_oversize_body(self) -> None:
        with pytest.raises(ValidationError, match="超限"):
            await service.create_skill(
                FakeDB(),  # type: ignore[arg-type]
                name="big_skill",
                title="T",
                description="D",
                stage_key="parse",
                body_md="填" * (SKILL_BODY_MAX_CHARS + 1),
            )

    async def test_rejects_unknown_stage(self) -> None:
        with pytest.raises(ValidationError, match="非法"):
            await service.create_skill(
                FakeDB(),  # type: ignore[arg-type]
                name="stage_skill",
                title="T",
                description="D",
                stage_key="not_a_stage",
                body_md="正文",
            )

    @pytest.mark.parametrize("field", ["title", "description"])
    async def test_rejects_empty_required_text(self, field: str) -> None:
        kw: dict[str, Any] = {
            "name": "text_skill",
            "title": "T",
            "description": "D",
            "stage_key": "parse",
            "body_md": "正文",
        }
        kw[field] = "   "
        with pytest.raises(ValidationError, match="不可为空"):
            await service.create_skill(FakeDB(), **kw)  # type: ignore[arg-type]


class TestCreateSkillEnabledPolicy:
    async def test_user_created_is_enabled(self) -> None:
        db = FakeDB()
        row = await service.create_skill(
            db,  # type: ignore[arg-type]
            name="user_skill",
            title="T",
            description="D",
            stage_key="parse",
            body_md="正文",
            created_by="user",
        )
        assert row.enabled is True
        assert row.created_by == "user"

    async def test_llm_created_is_disabled_pending_review(self) -> None:
        """产品口径①A：LLM 自建默认禁用，待人审."""
        db = FakeDB()
        row = await service.create_skill(
            db,  # type: ignore[arg-type]
            name="llm_skill",
            title="T",
            description="D",
            stage_key="parse",
            body_md="正文",
            created_by="llm",
        )
        assert row.enabled is False
        assert row.created_by == "llm"

    async def test_llm_skill_invisible_until_enabled(self) -> None:
        """端到端：LLM 建 → 注册表不可见 → 启用后可见."""
        db = FakeDB()
        await service.create_skill(
            db,  # type: ignore[arg-type]
            name="llm_hidden",
            title="T",
            description="D",
            stage_key="parse",
            body_md="正文",
            created_by="llm",
        )
        registry.invalidate()
        assert "llm_hidden" not in {c.name for c in await registry.list_skills(db)}  # type: ignore[arg-type]

        db.rows[0].enabled = True
        registry.invalidate()
        assert "llm_hidden" in {c.name for c in await registry.list_skills(db)}  # type: ignore[arg-type]


class TestUpdateSkill:
    async def test_optimistic_lock_conflict(self) -> None:
        db = FakeDB([_row("upd_skill", version=3)])
        with pytest.raises(ConflictError, match="刷新后重试"):
            await service.update_skill(db, "upd_skill", title="新标题", expected_version=2)  # type: ignore[arg-type]

    async def test_optimistic_lock_success_bumps_version(self) -> None:
        db = FakeDB([_row("upd_skill", version=3)])
        row = await service.update_skill(db, "upd_skill", title="新标题", expected_version=3)  # type: ignore[arg-type]
        assert row.version == 4
        assert row.title == "新标题"

    async def test_three_state_none_keeps_value(self) -> None:
        db = FakeDB([_row("upd_skill", title="原标题")])
        row = await service.update_skill(db, "upd_skill", enabled=False)  # type: ignore[arg-type]
        assert row.title == "原标题"
        assert row.enabled is False

    async def test_missing_raises_not_found(self) -> None:
        with pytest.raises(NotFoundError):
            await service.get_skill(FakeDB([]), "ghost")  # type: ignore[arg-type]

    async def test_update_validates_body(self) -> None:
        db = FakeDB([_row("upd_skill")])
        with pytest.raises(ValidationError, match="不可为空"):
            await service.update_skill(db, "upd_skill", body_md="   ")  # type: ignore[arg-type]


class TestDeleteAndReset:
    async def test_delete_removes_row(self) -> None:
        db = FakeDB([_row("del_skill")])
        await service.delete_skill(db, "del_skill")  # type: ignore[arg-type]
        assert db.deleted and db.deleted[0].name == "del_skill"

    async def test_delete_then_falls_back_to_builtin(self) -> None:
        """删除用户覆盖 ⇒ 回退内置（parse_score 存在内置）."""
        db = FakeDB([_row("parse_score", body_md="用户覆盖")])
        await service.delete_skill(db, "parse_score")  # type: ignore[arg-type]
        registry.invalidate()
        hit = await registry.find_skill("parse_score", db)  # type: ignore[arg-type]
        assert hit is not None and hit.builtin is True


class TestViews:
    def test_builtin_view_shape(self) -> None:
        text = (
            "---\n"
            "name: v_skill\n"
            "title: T\n"
            "description: D\n"
            "version: '1.0.0'\n"
            "stage_key: parse\n"
            "---\n"
            "正文\n"
        )
        c = parse_skill_md(text, builtin=True)
        view = service.contract_to_view(c, editable=False)
        assert view["builtin"] is True
        assert view["createdBy"] == "builtin"
        assert view["virtualPath"] == "/__builtin_skills__/v_skill/SKILL.md"
        assert view["editable"] is False

    def test_user_view_shape(self) -> None:
        view = service.row_to_view(_row("u_skill", created_by="llm", enabled=False))
        assert view["builtin"] is False
        assert view["createdBy"] == "llm"
        assert view["enabled"] is False
        assert view["virtualPath"] == "/__user_skills__/u_skill/SKILL.md"
        assert view["optimisticVersion"] == 1
