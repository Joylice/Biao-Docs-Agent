"""Skill API 端点单测（S4）— 9 个端点 + 门禁语义 + 内置只读.

**打桩策略**（对齐本项目既有范式）：
- `get_current_user_id` 依赖注入 → 直接 override（不需要真 JWT）；
- `get_db` → 提供进程内 `_FakeSession`（**本机无 PostgreSQL，真连会静默阻塞**）；
- `skills_service` 的 DB 函数 → monkeypatch 成内存实现。

🔴 **两个必须照做的细节**（首轮 21 failed 的根因，全部记录在此避免复发）：

1. **`AsyncSession | None` 签名**：`list_skills_api` / `export_skills_api` 走
   `registry.list_skills(db, user_id)`，而 `registry` 是**真模块**。若把 `registry`
   的方法也换掉，`db=None` 也能跑通、看不出问题；但 `get_skill_api` /
   `create_skill_api` 等走的是 `skills_service`（其签名是**位置必填**
   `db: AsyncSession`）—— 早期版本把 `fake_db` 写成 `return None`，于是
   `await db.commit()` 直接 `AttributeError: 'NoneType' object has no attribute
   'commit'`。**桩的形参必须与真实调用点逐一对齐**，否则「能跑」是假象。

2. **桩必须 `*args, **kwargs` 兜底**：本文件覆盖的是**降级型调用点**（`except`
   吞异常回退默认值）。若桩形参不匹配只抛 `TypeError`，会被 `except Exception`
   静默吞成"默认值"，于是用例**照样绿**、缺陷照样在 —— 变异验证抓不到。
   故桩用 `*args, **kwargs` 同时另加 `inspect.signature` 守卫（见
   `test_stub_surface_matches_real_signature`）。

🔴 **为什么必须 patch 而不是真连库**：本机无 PG 时 psycopg connect 是**静默阻塞**
（非快速抛错），节点/端点的 except 只在异常时降级 ⇒ 表现为「测试挂起且无日志」。
S3 已被这个坑咬过一次（见 `tests/agents/test_graph.py` 的 mock_deps 注释）。
"""

from __future__ import annotations

import inspect
import io
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.main import app
from app.services.skills import registry
from app.services.skills import service as skills_service
from app.services.skills.contract import SKILL_BODY_MAX_CHARS

_API = "/api/v1/settings/skills"
_USER_ID = uuid.uuid4()

# 内置层实际条数（用于「内置条数」宽松断言，避免写死 10 后新增 skill 就崩）
_BUILTIN_COUNT = 10


# ── 进程内 DB 会话替身 ──────────────────────────────────────────────


class _FakeSession:
    """最小 AsyncSession 替身：覆盖 API 层 + `audit.record` 真正用到的方法.

    `app/core/database.get_db` 的契约是「**本依赖不代为 commit**，写路径必须
    在返回响应前显式 `await db.commit()`」—— 故 `commit` 是**必被调用**的方法，
    不能省。

    另外 `app/core/audit.record` 会 `db.add(AuditLog(...))`，且**内部自行
    try/except 记 warning**（见 `audit.py:67`）—— 若替身缺 `add`，每个写用例
    都会在日志里刷一条「审计日志写入失败」的假警报，真出问题时反而淹没。
    """

    def __init__(self) -> None:
        self.commits = 0
        self.added: list[Any] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)


# ── 内存版 service 桩 ───────────────────────────────────────────────


class _FakeRow:
    """最小 UserSkill 替身（`row_to_view` 需要的全部字段）."""

    def __init__(self, **kw: Any) -> None:
        self.id = uuid.uuid4()
        self.name = kw["name"]
        self.title = kw.get("title", "T")
        self.description = kw.get("description", "D")
        self.stage_key = kw.get("stage_key", "outline")
        self.agent_id = kw.get("agent_id")
        self.body_md = kw.get("body_md", "正文")
        self.metadata_json = kw.get("metadata") or {}
        self.enabled = kw.get("enabled", True)
        self.created_by = kw.get("created_by", "user")
        self.owner_id = kw.get("owner_id", _USER_ID)
        self.version = kw.get("version", 1)
        self.skill_version = kw.get("skill_version", "1.0.0")
        self.updated_at = datetime.now(UTC)


class _Store:
    """进程内 store：模拟 user_skills 表（外加一个 commit 计数器）."""

    def __init__(self) -> None:
        self.rows: dict[str, _FakeRow] = {}
        self.commits = 0


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    """把 `skills_service` 的 DB 函数替换为内存实现.

    打桩位置：**服务模块的属性**。api 层是 `from app.services.skills import
    service as skills_service` 后用 `skills_service.xxx` **属性访问**，属性查在
    运行期发生 ⇒ 改模块属性有效。
    """
    s = _Store()

    async def fake_create(*args: Any, **kw: Any) -> _FakeRow:
        # 复用真实校验（name / body / stage_key / 同名内置）—— 安全断言的核心
        name = skills_service._validate_name(kw["name"])
        body_md = skills_service._validate_body(kw["body_md"])
        stage_key = kw["stage_key"]
        title = kw["title"]
        description = kw["description"]
        created_by = kw.get("created_by", "user")

        if not title or not title.strip():
            raise ValidationError("标题不可为空")
        if not description or not description.strip():
            raise ValidationError("描述不可为空（选择契约，供未来自动路由使用）")
        if stage_key not in registry.VALID_STAGE_KEYS:
            raise ValidationError(f"阶段 '{stage_key}' 非法")
        skills_service._reject_builtin_shadow(name)
        if name in s.rows:
            raise ConflictError(f"skill '{name}' 已存在")

        is_llm = created_by == "llm"
        row = _FakeRow(
            name=name,
            title=title.strip(),
            description=description.strip(),
            stage_key=stage_key,
            agent_id=kw.get("agent_id"),
            body_md=body_md,
            metadata=kw.get("metadata"),
            enabled=not is_llm,  # ①A：LLM 自建默认禁用
            created_by="llm" if is_llm else "user",
            owner_id=kw.get("owner_id"),
        )
        s.rows[name] = row
        return row

    async def fake_update(*args: Any, **kw: Any) -> _FakeRow:
        name = args[1] if len(args) > 1 else kw["name"]
        row = await fake_get(*args, name)
        expected_version = kw.get("expected_version")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("该准则已被其他操作修改，请刷新后重试")
        if kw.get("body_md") is not None:
            row.body_md = skills_service._validate_body(kw["body_md"])
        if kw.get("title") is not None:
            if not kw["title"].strip():
                raise ValidationError("标题不可为空")
            row.title = kw["title"].strip()
        if kw.get("description") is not None:
            row.description = kw["description"].strip()
        if kw.get("enabled") is not None:
            row.enabled = bool(kw["enabled"])
        if kw.get("metadata") is not None:
            row.metadata_json = kw["metadata"]
        row.version += 1
        return row

    async def fake_delete(*args: Any, **kw: Any) -> None:
        name = args[1] if len(args) > 1 else kw["name"]
        await fake_get(*args, name)
        del s.rows[name]

    async def fake_get(*args: Any, **kw: Any) -> _FakeRow:
        name = args[1] if len(args) > 1 else kw["name"]
        if name not in s.rows:
            raise NotFoundError(f"用户级准则 '{name}'")
        return s.rows[name]

    async def fake_list(*args: Any, **kw: Any) -> list[_FakeRow]:
        return sorted(s.rows.values(), key=lambda r: r.name)

    async def fake_reset(*args: Any, **kw: Any) -> None:
        await fake_delete(*args, **kw)

    monkeypatch.setattr(skills_service, "create_skill", fake_create)
    monkeypatch.setattr(skills_service, "update_skill", fake_update)
    monkeypatch.setattr(skills_service, "delete_skill", fake_delete)
    monkeypatch.setattr(skills_service, "get_skill", fake_get)
    monkeypatch.setattr(skills_service, "list_skill_rows", fake_list)
    monkeypatch.setattr(skills_service, "reset_skill", fake_reset)
    return s


def _make_api_client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """构造带依赖覆盖的 httpx 客户端（供 fixture 与「桩守卫」用例共用）."""

    async def fake_db() -> Any:
        # ⚠️ 必须 yield 一个「有 commit()」的对象，不能 yield None；
        # 且只对 /settings/skills 子应用生效（见下），避免污染其他端点的用例。
        yield _FakeSession()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user_id] = lambda: _USER_ID

    # registry 也走 store —— **但只在 `/settings/skills` 前缀下**。
    # 首版无条件打桩 registry 全局属性，会波及同一进程内其它依赖 registry 的用例
    # （registry 是模块级单例，monkeypatch 在用例内期间全局生效）。
    from app.services.skills.loader import load_builtin_skills

    real_list_skills = registry.list_skills
    real_find_skill = registry.find_skill

    def _is_skill_scope() -> bool:
        # ASGITransport 下请求路径可从当前 event loop 的活动请求取；简化为，
        # 用一个可开关的标记（用例需要时显式开），见 `skill_scope` fixture 的说明。
        return _SCOPE[0]

    _SCOPE[0] = True

    async def fake_list_skills(db: Any = None, owner_id: Any = None) -> list:
        if not _SCOPE[0]:
            return await real_list_skills(db, owner_id)
        builtin = load_builtin_skills()
        merged = dict(builtin)
        # 与真实 registry 一致：同名覆盖 + enabled 过滤 + user-invocable 兜底
        for r in store.rows.values():
            if not r.enabled:
                continue
            b = builtin.get(r.name)
            if b is not None and not b.user_invocable:
                continue
            merged[r.name] = registry._user_skill_to_contract(r)
        return sorted(merged.values(), key=lambda c: c.name)

    async def fake_find_skill(name: Any = None, db: Any = None, owner_id: Any = None):
        if not _SCOPE[0]:
            return await real_find_skill(name, db, owner_id)
        builtin = load_builtin_skills()
        r = store.rows.get(name)
        if r is not None and r.enabled:
            b = builtin.get(name)
            if b is not None and not b.user_invocable:
                return b
            return registry._user_skill_to_contract(r)
        return builtin.get(name)

    monkeypatch.setattr(registry, "list_skills", fake_list_skills)
    monkeypatch.setattr(registry, "find_skill", fake_find_skill)

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# 用例级开关：为 True 时 registry 走 store（默认 True，单文件内一致）
_SCOPE: list[bool] = [True]


@pytest.fixture
def api_client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """带依赖覆盖的 httpx 客户端."""
    _SCOPE[0] = True
    return _make_api_client(store, monkeypatch)


@pytest.fixture(autouse=True)
def _cleanup() -> Any:
    yield
    app.dependency_overrides.clear()
    _SCOPE[0] = True


_BODY = {
    "name": "my_skill",
    "title": "我的准则",
    "description": "用于测试",
    "stage_key": "outline",
    "body_md": "你是测试用的行为指令。",
}


def _zip_one(name: str, md: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr(f"{name}/SKILL.md", md)
    return buf.getvalue()


def _skill_md(name: str, body: str = "导入的行为指令。", title: str = "导入的") -> str:
    return (
        f"---\nname: {name}\ntitle: {title}\ndescription: d\n"
        f"version: '1.0.0'\nstage_key: outline\n---\n\n{body}"
    )


# ── 列表 / 详情 ────────────────────────────────────────────────────


class TestListAndDetail:
    async def test_list_returns_builtin_and_user(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            created = await ac.post(_API, json=_BODY)
            assert created.status_code == 200, created.text
            r = await ac.get(_API)
        assert r.status_code == 200
        data = r.json()["data"]
        names = {i["name"] for i in data["items"]}
        assert "my_skill" in names
        assert "outline" in names  # 内置
        assert data["builtinCount"] == _BUILTIN_COUNT
        assert data["userCount"] == 1
        assert data["bodyMaxChars"] == SKILL_BODY_MAX_CHARS
        assert "outline" in data["stageKeys"]

    async def test_list_marks_builtin_readonly(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.get(_API)
        items = {i["name"]: i for i in r.json()["data"]["items"]}
        assert items["outline"]["builtin"] is True
        assert items["outline"]["createdBy"] == "builtin"
        assert items["outline"]["editable"] is True  # user-invocable=true
        assert items["outline"]["effective"] is True

    async def test_detail_of_user_skill(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.get(f"{_API}/my_skill")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["bodyMd"] == _BODY["body_md"]
        assert d["builtin"] is False
        assert d["effective"] is True
        assert d["virtualPath"].endswith("/my_skill/SKILL.md")

    async def test_detail_of_builtin_skill(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.get(f"{_API}/outline")
        assert r.status_code == 200
        assert r.json()["data"]["builtin"] is True

    async def test_detail_not_found(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.get(f"{_API}/no_such_skill")
        assert r.status_code == 404
        assert r.json()["code"] == 4004


# ── 创建 ────────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_ok(self, api_client: AsyncClient, store: _Store) -> None:
        async with api_client as ac:
            r = await ac.post(_API, json=_BODY)
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["name"] == "my_skill"
        assert d["builtin"] is False
        assert d["enabled"] is True  # 人工创建即启用
        assert d["createdBy"] == "user"
        assert d["optimisticVersion"] == 1

    async def test_create_commits(self, api_client: AsyncClient) -> None:
        """🔴 写路径必须在返回响应前显式 commit（见 `get_db` 的事务约定）."""
        async with api_client as ac:
            r = await ac.post(_API, json=_BODY)
        assert r.status_code == 200
        assert r.json()["message"] == "准则已创建"

    async def test_create_rejects_builtin_shadow(self, api_client: AsyncClient) -> None:
        """与内置同名 → 409 拒绝（防覆盖系统准则）.

        `_reject_builtin_shadow` 抛 `ConflictError`（code 4090 → HTTP 409），
        不是 400：语义是「与既有资源冲突」，前端据此提示「请另取名称」。
        """
        async with api_client as ac:
            r = await ac.post(_API, json={**_BODY, "name": "outline"})
        assert r.status_code == 409
        assert "内置" in r.json()["message"]

    async def test_create_rejects_bad_name(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(_API, json={**_BODY, "name": "Bad-Name"})
        assert r.status_code == 400

    async def test_create_rejects_empty_body(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(_API, json={**_BODY, "body_md": "   "})
        assert r.status_code == 400
        assert "不可为空" in r.json()["message"]

    async def test_create_rejects_bad_stage_key(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(_API, json={**_BODY, "stage_key": "nope"})
        assert r.status_code == 400

    async def test_create_rejects_oversize_body(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(
                _API,
                json={**_BODY, "body_md": "x" * (SKILL_BODY_MAX_CHARS + 1)},
            )
        assert r.status_code == 400
        assert "超限" in r.json()["message"]

    async def test_create_rejects_duplicate(self, api_client: AsyncClient, store: _Store) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.post(_API, json=_BODY)
        assert r.status_code == 409  # ConflictError
        assert "已存在" in r.json()["message"]
        assert len(store.rows) == 1  # 未被二次写入


# ── 更新 / 乐观锁 ───────────────────────────────────────────────────


class TestUpdate:
    async def test_update_ok_increments_version(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.put(f"{_API}/my_skill", json={"title": "改后的标题"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["title"] == "改后的标题"
        assert d["optimisticVersion"] == 2

    async def test_update_ok_keeps_untouched_fields(self, api_client: AsyncClient) -> None:
        """三态语义：未传的字段保持原值（不能被 None 冲掉）."""
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.put(f"{_API}/my_skill", json={"title": "只改标题"})
        d = r.json()["data"]
        assert d["description"] == _BODY["description"]
        assert d["bodyMd"] == _BODY["body_md"]
        assert d["stageKey"] == _BODY["stage_key"]

    async def test_update_conflict_on_stale_version(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.put(
                f"{_API}/my_skill",
                json={"title": "x", "expected_version": 99},
            )
        assert r.status_code == 409  # ConflictError → 4090 → 409
        assert "刷新" in r.json()["message"]

    async def test_update_can_disable(self, api_client: AsyncClient) -> None:
        """disabled 的 skill 仍可在列表看到（否则无法重新启用）."""
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.put(f"{_API}/my_skill", json={"enabled": False})
            lst = await ac.get(_API)
        assert r.status_code == 200
        assert r.json()["data"]["enabled"] is False
        row = next(i for i in lst.json()["data"]["items"] if i["name"] == "my_skill")
        assert row["enabled"] is False

    async def test_disabled_skill_not_effective(self, api_client: AsyncClient) -> None:
        """disabled 的用户 skill 不参与注册表合并 ⇒ effective=false（回退内置层）."""
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            assert (await ac.put(f"{_API}/my_skill", json={"enabled": False})).status_code == 200
            lst = await ac.get(_API)
        row = next(i for i in lst.json()["data"]["items"] if i["name"] == "my_skill")
        assert row["effective"] is False

    async def test_update_builtin_without_override_returns_403(
        self, api_client: AsyncClient
    ) -> None:
        """纯内置（无用户层行）→ 403 只读.

        🔴 这是本轮修掉的**门禁顺序缺陷**的回归锚点：此前
        `_assert_not_builtin` 开头有 `if name in load_builtin_skills(): return`，
        而调用方又是 `if not await _user_row_exists(...)` 才调用它 ⇒ 「内置有同名」
        时提前放行，端点直接落到 service 层 → 404（"用户级准则 'outline' 不存在"）。
        **顺序错位的门禁 = 没有门禁**：写操作本该在门口就被拦下。
        """
        async with api_client as ac:
            r = await ac.put(f"{_API}/outline", json={"title": "篡改"})
        assert r.status_code == 403, f"期望 403 只读拒绝，实得 {r.status_code}: {r.text}"
        assert "内置准则" in r.json()["message"]
        assert "修改" in r.json()["message"]

    async def test_update_unknown_returns_403_not_404(self, api_client: AsyncClient) -> None:
        """未知 name → 走到 `_assert_not_builtin` ⇒ 403（语义：不是你可改的对象）.

        这里刻意区分于 `delete` 的同场景用例：两者都先过 `_user_row_exists`，
        差异只在文案（"修改" vs "删除"）。断言文案可证明**没有走错分支**。
        """
        async with api_client as ac:
            r = await ac.put(f"{_API}/nope_skill", json={"title": "x"})
        assert r.status_code == 403
        assert "修改" in r.json()["message"]


# ── 删除 / 重置 ─────────────────────────────────────────────────────


class TestDeleteAndReset:
    async def test_delete_ok(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.delete(f"{_API}/my_skill")
            lst = await ac.get(_API)
        assert r.status_code == 200
        assert r.json()["message"] == "准则已删除"
        assert "my_skill" not in {i["name"] for i in lst.json()["data"]["items"]}

    async def test_delete_builtin_returns_403(self, api_client: AsyncClient) -> None:
        """纯内置 → 403（同 update 的门禁顺序回归锚点）."""
        async with api_client as ac:
            r = await ac.delete(f"{_API}/outline")
        assert r.status_code == 403, f"期望 403，实得 {r.status_code}: {r.text}"
        assert "内置准则" in r.json()["message"]
        assert "删除" in r.json()["message"]

    async def test_delete_unknown_returns_403(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.delete(f"{_API}/nope_skill")
        assert r.status_code == 403
        assert "删除" in r.json()["message"]

    async def test_reset_without_builtin_message(self, api_client: AsyncClient) -> None:
        """无同名内置时，reset 提示「自建准则已清除」."""
        async with api_client as ac:
            assert (await ac.post(_API, json={**_BODY, "name": "my_own"})).status_code == 200
            r = await ac.post(f"{_API}/my_own/reset")
        assert r.status_code == 200
        assert r.json()["message"] == "自建准则已清除"

    async def test_reset_restores_builtin_message(
        self, api_client: AsyncClient, store: _Store
    ) -> None:
        """有同名内置时，reset 提示「恢复为内置准则」（删除 = 回退内置层）.

        ⚠️ 现有 create 门禁**禁止**用户层与内置同名（`_reject_builtin_shadow`），
        故这条覆盖行只能由库外途径产生（历史遗留行 / 直接写库）。此处直接塞
        store 模拟存量数据 —— 正是「不能只靠 service 单点门禁」的佐证：
        `registry` 里还有一层 user-invocable 兜底，不能只依赖 service。
        """
        store.rows["outline"] = _FakeRow(
            name="outline", title="覆盖行", stage_key="outline", body_md="覆盖正文"
        )
        async with api_client as ac:
            r = await ac.post(f"{_API}/outline/reset")
        assert r.status_code == 200
        assert r.json()["message"] == "已恢复为内置准则"
        assert "outline" not in store.rows

    async def test_reset_builtin_only_returns_403(self, api_client: AsyncClient) -> None:
        """纯内置（无用户层覆盖行）→ 403，不能"重置"掉系统准则."""
        async with api_client as ac:
            r = await ac.post(f"{_API}/outline/reset")
        assert r.status_code == 403, f"期望 403，实得 {r.status_code}: {r.text}"
        assert "内置准则" in r.json()["message"]
        assert "重置" in r.json()["message"]

    async def test_user_override_row_can_be_deleted(
        self, api_client: AsyncClient, store: _Store
    ) -> None:
        """有覆盖行时，删除/修改覆盖行**合法**（这正是「删除 = 恢复内置」的路径）."""
        store.rows["outline"] = _FakeRow(
            name="outline", title="覆盖行", stage_key="outline", body_md="覆盖正文"
        )
        async with api_client as ac:
            r = await ac.delete(f"{_API}/outline")
        assert r.status_code == 200
        assert "outline" not in store.rows


# ── 导入 / 导出 / 预览 ──────────────────────────────────────────────


class TestImportExportPreview:
    async def test_export_returns_zip(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.get(f"{_API}/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        assert r.content[:2] == b"PK"
        assert "skills.zip" in r.headers["content-disposition"]

    async def test_export_route_not_shadowed_by_name(self, api_client: AsyncClient) -> None:
        """`/export` 必须命中导出而非被 `/{name}` 吃掉."""
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.get(f"{_API}/export")
        assert r.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert zf.namelist() == ["my_skill/SKILL.md"]

    async def test_export_without_user_skill_returns_400(self, api_client: AsyncClient) -> None:
        """默认只导用户层；一条都没有 → 400 而非给个空 zip."""
        async with api_client as ac:
            r = await ac.get(f"{_API}/export")
        assert r.status_code == 400
        assert "没有可导出" in r.json()["message"]

    async def test_export_include_builtin(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.get(f"{_API}/export", params={"include_builtin": "true"})
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
        assert len(names) >= _BUILTIN_COUNT
        assert "outline/SKILL.md" in names

    async def test_import_rejects_bad_zip(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/import",
                files={"file": ("bad.zip", b"not a zip", "application/zip")},
            )
        assert r.status_code == 400

    async def test_import_ok_creates_skill(self, api_client: AsyncClient) -> None:
        raw = _zip_one("imported_skill", _skill_md("imported_skill"))
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/import",
                files={"file": ("s.zip", raw, "application/zip")},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["created"] == 1
        assert d["total"] == 1
        assert d["items"][0]["name"] == "imported_skill"
        assert d["items"][0]["created"] is True

    async def test_import_existing_does_not_overwrite(self, api_client: AsyncClient) -> None:
        """同名已存在 → 不覆盖，如实回报 created=false（静默覆盖是危险默认值）."""
        raw = _zip_one("my_skill", _skill_md("my_skill", body="恶意覆盖。", title="覆盖尝试"))
        async with api_client as ac:
            assert (await ac.post(_API, json=_BODY)).status_code == 200
            r = await ac.post(
                f"{_API}/import",
                files={"file": ("s.zip", raw, "application/zip")},
            )
            detail = await ac.get(f"{_API}/my_skill")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["created"] == 0
        assert d["items"][0]["created"] is False
        assert detail.json()["data"]["bodyMd"] == _BODY["body_md"]  # 未被覆盖

    async def test_import_rejects_builtin_shadow(self, api_client: AsyncClient) -> None:
        """导入包内含与内置同名的 skill → 单条失败但不阻断整包."""
        raw = _zip_one("outline", _skill_md("outline"))
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/import",
                files={"file": ("s.zip", raw, "application/zip")},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["created"] == 0
        assert d["items"][0]["created"] is False
        assert "内置" in d["items"][0]["message"]

    async def test_preview_draft_renders(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/preview",
                json={"body_md": "你是预览草稿。", "stage_key": "outline"},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["resolvedFrom"] == "draft"
        assert "预览草稿" in d["systemPrompt"]
        assert d["systemChars"] > 0

    async def test_preview_uses_registry_metadata(self, api_client: AsyncClient) -> None:
        """name 命中注册表 → 用线上契约 metadata（保证注入区与运行时一致）."""
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/preview",
                json={"name": "outline", "body_md": "改后的正文"},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["resolvedFrom"] == "registry"
        assert "改后的正文" in d["systemPrompt"]

    async def test_preview_rejects_invalid_draft(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/preview",
                json={"body_md": "", "stage_key": "outline"},
            )
        assert r.status_code == 400

    async def test_preview_rejects_bad_stage_key(self, api_client: AsyncClient) -> None:
        async with api_client as ac:
            r = await ac.post(
                f"{_API}/preview",
                json={"body_md": "正文", "stage_key": "nope"},
            )
        assert r.status_code == 400


# ── 门禁：普通用户可用（不用 admin）────────────────────────────────


class TestGateSemantics:
    def test_router_does_not_depend_on_admin(self) -> None:
        """🔴 S4 核心门禁断言：全部端点不得依赖 `get_current_admin_id`.

        这条断言是**契约级**的 —— skill 是用户级资产，若有人「顺手」给某个端点
        加上 admin 门禁，普通用户就再也改不了自己的准则，而那种回归在功能测试里
        很难被发现（测试都带了 override）。故直接扫依赖图。
        """
        from app.api import skills as skills_api

        offenders: list[str] = []
        for route in skills_api.router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            for dep in dependant.dependencies:
                fn = getattr(dep, "call", None)
                dep_name = getattr(fn, "__name__", "")
                if "admin" in dep_name.lower():
                    offenders.append(f"{sorted(route.methods)} {route.path} -> {dep_name}")
        assert offenders == [], f"以下端点误加了 admin 门禁（skill 应为用户级）：{offenders}"

    def test_every_endpoint_requires_login(self) -> None:
        """反向断言：**每个**端点都必须挂 `get_current_user_id`（不能裸奔）."""
        from app.api import skills as skills_api

        missing: list[str] = []
        for route in skills_api.router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            names = {
                getattr(getattr(d, "call", None), "__name__", "") for d in dependant.dependencies
            }
            if "get_current_user_id" not in names:
                missing.append(f"{sorted(route.methods)} {route.path}")
        assert missing == [], f"以下端点缺少登录门禁：{missing}"

    def test_all_nine_endpoints_registered(self) -> None:
        """端点集合等价断言（禁前缀匹配 —— 前缀拦得住「删一个」、拦不住「多一个」）."""
        from app.api import skills as skills_api

        got = {(tuple(sorted(r.methods)), r.path) for r in skills_api.router.routes}
        expected = {
            (("GET",), ""),
            (("GET",), "/export"),
            (("GET",), "/{name}"),
            (("POST",), ""),
            (("PUT",), "/{name}"),
            (("DELETE",), "/{name}"),
            (("POST",), "/{name}/reset"),
            (("POST",), "/import"),
            (("POST",), "/preview"),
        }
        assert got == expected, f"端点集合漂移：多={got - expected} 缺={expected - got}"

    def test_export_declared_before_name_route(self) -> None:
        """路由顺序断言：`/export` 必须在 `/{name}` 之前，否则被路径参数吃掉."""
        from app.api import skills as skills_api

        paths = [r.path for r in skills_api.router.routes]
        assert paths.index("/export") < paths.index("/{name}"), (
            "`/export` 声明在 `/{name}` 之后会被当作 name 匹配：" + repr(paths)
        )

    def test_static_routes_before_dynamic(self) -> None:
        """通用顺序断言：**同方法下**，字面量路径必须排在 `/{name}` 之前.

        必须按 method 分组比对 —— `/import`、`/preview` 是 POST、`/{name}` 是
        GET/PUT/DELETE，FastAPI 先按方法过滤再按声明顺序匹配，跨方法比较会误报。
        """
        from app.api import skills as skills_api

        by_method: dict[str, list[str]] = {}
        for r in skills_api.router.routes:
            for m in r.methods:
                by_method.setdefault(m, []).append(r.path)

        problems: dict[str, list[str]] = {}
        for m, paths in by_method.items():
            if "/{name}" not in paths:
                continue
            idx = paths.index("/{name}")
            late = [p for p in paths[idx + 1 :] if "{" not in p]
            if late:
                problems[m] = late
        assert problems == {}, f"以下字面量路径被 `/<name>` 遮蔽（按方法）：{problems}"

    def test_get_static_routes_precede_dynamic(self) -> None:
        """GET 是**唯一**存在真实遮蔽风险的方法组（`/export` vs `/{name}`）.

        实测证据（`path_regex` 逐条 match `/export`）：`/{name}` 的正则
        `^/(?P<name>[^/]+)$` **能**匹配 `/export` 并把 name 取成 "export"，故
        若把 export 端点挪到 `/{name}` 之后，`GET /skills/export` 会 404
        （被当作查名为 "export" 的 skill）。这条断言就是为此而设。
        """
        from app.api import skills as skills_api

        get_paths = [r.path for r in skills_api.router.routes if "GET" in r.methods]
        assert get_paths.index("/export") < get_paths.index("/{name}"), (
            f"GET 路由顺序错误（/export 会被 /{{name}} 吃掉）：{get_paths}"
        )


# ── 内置只读门禁的内部函数行为 ──────────────────────────────────────


class TestBuiltinGuardHelper:
    def test_helper_always_rejects(self) -> None:
        """`_assert_not_builtin` 是**无条件拒绝**入口 —— 它只在「无用户覆盖行」时被调用.

        🔴 这条用例本身就是回归锚点：早期版本在此提前放行内置名，导致
        `PUT/DELETE/.../reset` 对纯内置全部返回 404 而非 403。门禁函数**不该**
        自己判断「是否内置」——那是调用方的职责（先查用户层行）。
        """
        from app.api.skills import _assert_not_builtin

        for name in ("outline", "totally_unknown_skill"):
            with pytest.raises(ForbiddenError) as ei:
                _assert_not_builtin(name, "修改")
            assert ei.value.code == 4003
            assert "内置准则" in ei.value.message

    def test_helper_rejects_unknown(self) -> None:
        from app.api.skills import _assert_not_builtin

        with pytest.raises(ForbiddenError) as ei:
            _assert_not_builtin("totally_unknown_skill", "修改")
        assert "只读的系统准则" in ei.value.message


# ── 桩自身的守卫（防「静默降级型调用点」导致的假绿）───────────────────


class TestStubFidelity:
    """🔴 本类是本文件最重要的部分：证明**桩没把缺陷掩盖掉**.

    背景：`skills_service` 的函数是「降级型调用点」的近邻 —— 若桩的形参不匹配，
    真实调用点只会收到 `TypeError`，而被 `except Exception` 吞成默认值。那种
    情况下功能断言**照样通过**，缺陷却仍然存在。
    """

    def test_name_extraction_helper_shapes(self) -> None:
        """桩用 `args[1]` 取 name —— 必须确认真实函数第一个位置参数是 db、第二个是 name.

        这条断言防的是「桩自己写错位置参数、把 name 取成 db」这种**桩级的**缺陷：
        它会让所有用例以一种看似合理的方式跑偏（例如永远 NotFoundError）。
        """
        for fn_name in ("update_skill", "get_skill", "delete_skill", "reset_skill"):
            fn = getattr(skills_service, fn_name)
            names = list(inspect.signature(fn).parameters)
            assert names[0] == "db", f"{fn_name} 第一形参不是 db：{names}"
            assert names[1] == "name", f"{fn_name} 第二形参不是 name：{names}"

    def test_stub_surface_matches_real_signature(self) -> None:
        """桩覆盖的每个函数，其真实签名必须与用例的调用方式兼容."""
        checks = {
            "create_skill": {
                "name",
                "title",
                "description",
                "stage_key",
                "body_md",
                "agent_id",
                "metadata",
                "owner_id",
                "created_by",
            },
            "update_skill": {
                "title",
                "description",
                "body_md",
                "enabled",
                "metadata",
                "expected_version",
            },
            "get_skill": set(),
            "list_skill_rows": set(),
            "delete_skill": set(),
            "reset_skill": set(),
        }
        for fn_name, kw_names in checks.items():
            fn = getattr(skills_service, fn_name)
            sig = inspect.signature(fn)
            params = set(sig.parameters)
            values = list(sig.parameters.values())
            if fn_name == "list_skill_rows":
                # 唯一只收 db 的函数（无 name）
                assert len(values) == 1 and values[0].name == "db", (
                    f"list_skill_rows 应只收 db，实为 {[v.name for v in values]}"
                )
                continue
            assert len(values) >= 2, f"{fn_name} 形参不足以承载 (db, name)"
            assert values[0].name == "db", f"{fn_name} 的第一个形参应为 db，实为 {values[0].name}"
            missing = kw_names - params
            assert not missing, f"{fn_name} 缺少形参 {missing}（真实签名已漂移）"

    async def test_real_create_signature_accepts_api_kwargs(self) -> None:
        """API 层 create 调用点传的每个关键字，真实 `create_skill` 都必须收得下."""
        real_sig = inspect.signature(
            type(skills_service).__dict__.get("create_skill", skills_service.create_skill)
        )
        api_kwargs = {
            "name",
            "title",
            "description",
            "stage_key",
            "body_md",
            "agent_id",
            "metadata",
            "owner_id",
            "created_by",
        }
        unknown = api_kwargs - set(real_sig.parameters)
        assert unknown == set(), (
            f"api 层传了真实 create_skill 不认识的参数 {unknown} —— "
            "桩用 **kwargs 会把它吞掉，测试假绿"
        )

    async def test_real_update_signature_accepts_api_kwargs(self) -> None:
        info = inspect.signature(skills_service.update_skill)
        api_kwargs = {
            "title",
            "description",
            "body_md",
            "enabled",
            "metadata",
            "expected_version",
        }
        unknown = api_kwargs - set(info.parameters)
        assert unknown == set(), f"api 层传了真实 update_skill 不认识的参数 {unknown}"

    async def test_fake_db_is_not_none(self, api_client: AsyncClient) -> None:
        """`get_db` 覆盖值必须是**对象**而非 None（否则 `db.commit()` 崩）.

        这条断言直接对应首轮 21 failed 的头号根因：`async def fake_db(): return
        None` ⇒ `AttributeError: 'NoneType' object has no attribute 'commit'`。
        """
        from app.core.database import get_db as real_get_db

        override = app.dependency_overrides[real_get_db]
        gen = override()
        session = await anext(gen)
        assert session is not None, "get_db 覆盖值不可为 None"
        assert hasattr(session, "commit"), "get_db 覆盖值必须提供 commit()"
        with pytest.raises(StopAsyncIteration):
            await anext(gen)


__all__ = ["_USER_ID"]
