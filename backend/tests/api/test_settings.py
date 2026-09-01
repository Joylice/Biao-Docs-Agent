"""LLM 配置页面化 API 测试 — GET/PUT /settings/llm + POST /settings/llm/test.

说明（如实标注）：测试环境无 PostgreSQL，数据层经 dependency_overrides[get_db]
注入 mock/假会话（与 tests/api/test_projects.py、test_authorization.py 惯例一致）；
litellm 一律 mock，禁止真实调用。

C-1 管理员授权约定：autouse fixture 将 settings.admin_user_ids 置为 ADMIN_EMAIL
（项目唯一用户标识为 email）；管理员请求用 admin_headers（假会话回注 User 行），
普通用户请求用 auth_headers。
"""

import json
import sys
import time
import uuid
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit_log import AuditLog
from app.models.llm_settings import LlmSetting
from app.models.user import User
from app.services.infra import settings_service
from app.services.infra.settings import runtime
from app.services.infra.settings.runtime import RuntimeLlmConfig, invalidate_runtime_cache

ADMIN_USER_ID = uuid.uuid4()
ADMIN_EMAIL = "admin@example.com"


def _result(row: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _row(
    deepseek: str | None = None,
    dashscope: str | None = None,
    base: str | None = None,
    llm_mock: bool = False,
    embedding_model: str | None = None,
    embedding_key: str | None = None,
) -> LlmSetting:
    return LlmSetting(
        id=uuid.uuid4(),
        deepseek_api_key_enc=encrypt_secret(deepseek) if deepseek else None,
        dashscope_api_key_enc=encrypt_secret(dashscope) if dashscope else None,
        embedding_api_base=base,
        embedding_model=embedding_model,
        embedding_api_key_enc=encrypt_secret(embedding_key) if embedding_key else None,
        llm_mock=llm_mock,
    )


def _admin_user() -> User:
    return User(id=ADMIN_USER_ID, email=ADMIN_EMAIL, display_name="管理员")


def _admin_session_mock() -> AsyncMock:
    """仅用于无需 LlmSetting 行的端点（POST /test）：返回管理员 User 行."""
    session = AsyncMock()
    session.execute.return_value = _result(_admin_user())
    return session


class _FakeSettingsSession:
    """PUT 假会话：execute 按查询实体分派（User→管理员行/LlmSetting→配置行），
    记录 add/flush/commit；commit 时快照运行时缓存状态（W-1 时序断言）."""

    def __init__(self, row: LlmSetting | None = None, user: User | None = None) -> None:
        self.row = row
        self.user = user
        self.added: list = []
        self.flushed = False
        self.committed = False
        self.cache_alive_at_commit: bool | None = None

    async def execute(self, stmt):
        try:
            entity = stmt.column_descriptions[0].get("entity")
        except (AttributeError, IndexError):
            entity = None
        if entity is User:
            return _result(self.user)
        return _result(self.row)

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, LlmSetting):
            self.row = obj

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.cache_alive_at_commit = runtime._runtime_cache is not None
        self.committed = True


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token(str(uuid.uuid4()))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    token = create_access_token(str(ADMIN_USER_ID))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def override_db() -> Generator:
    """覆盖 get_db，用例结束清理."""

    def _override(session) -> None:
        app.dependency_overrides[get_db] = lambda: session

    yield _override
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_cache():
    invalidate_runtime_cache()
    yield
    invalidate_runtime_cache()


@pytest.fixture(autouse=True)
def _admin_config(monkeypatch):
    """默认配置管理员列表（C-1）；需要空列表的用例自行覆盖."""
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_EMAIL)


@pytest.fixture
def fake_litellm(monkeypatch):
    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


@pytest.fixture(autouse=True)
def _no_env_mock(monkeypatch):
    monkeypatch.setattr(settings, "llm_mock", False)


# ── 401 未登录（安全门禁）──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/settings/llm", None),
        ("PUT", "/api/v1/settings/llm", {"deepseek_api_key": ""}),
        ("POST", "/api/v1/settings/llm/test", {"target": "llm"}),
    ],
)
async def test_endpoints_without_auth_rejected(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    """无 Authorization 头 → 401/403（HTTPBearer 惯例）."""
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/settings/llm", None),
        ("PUT", "/api/v1/settings/llm", {"deepseek_api_key": ""}),
        ("POST", "/api/v1/settings/llm/test", {"target": "llm"}),
    ],
)
async def test_endpoints_with_invalid_token_return_401(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    """非法 token → 401 / code 4001."""
    resp = await client.request(
        method, path, json=body, headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 4001


# ── C-1 管理员授权（PUT/test 需 BID_ADMIN_USER_IDS 内账号）──


@pytest.mark.asyncio
async def test_put_by_non_admin_rejected_403(
    client: AsyncClient, override_db, auth_headers: dict[str, str]
) -> None:
    """非管理员 PUT 全局 LLM 配置 → 403 / code 4003（C-1）."""
    session = _FakeSettingsSession(
        row=None,
        user=User(id=uuid.uuid4(), email="other@example.com", display_name="普通用户"),
    )
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=auth_headers,
        json={
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == 4003
    assert session.committed is False


@pytest.mark.asyncio
async def test_test_endpoint_by_non_admin_rejected_403(
    client: AsyncClient, override_db, auth_headers: dict[str, str]
) -> None:
    """非管理员 POST /settings/llm/test → 403 / code 4003（C-1）."""
    session = AsyncMock()
    session.execute.return_value = _result(
        User(id=uuid.uuid4(), email="other@example.com", display_name="普通用户")
    )
    override_db(session)

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=auth_headers, json={"target": "llm"}
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == 4003


@pytest.mark.asyncio
async def test_admin_list_empty_rejected_with_hint(
    client: AsyncClient, override_db, admin_headers: dict[str, str], monkeypatch
) -> None:
    """白名单为空且 role≠admin → 拒绝写入（三期：role 判定优先，不放宽为任意登录用户）."""
    monkeypatch.setattr(settings, "admin_user_ids", "")
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 4003
    assert "仅限管理员" in body["message"]


# ── GET /settings/llm（普通登录可读）──


@pytest.mark.asyncio
async def test_get_llm_settings_masks_keys(
    client: AsyncClient, override_db, auth_headers: dict[str, str]
) -> None:
    """已配置：密钥脱敏展示 + configured 标志；响应不含明文；普通用户可读."""
    session = AsyncMock()
    session.execute.return_value = _result(
        _row(deepseek="sk-deep-secret-9876", dashscope="sk-dash-secret-5432")
    )
    override_db(session)

    resp = await client.get("/api/v1/settings/llm", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["deepseek_api_key"] == "sk-****9876"
    assert data["dashscope_api_key"] == "sk-****5432"
    assert data["deepseek_configured"] is True
    assert data["dashscope_configured"] is True
    # 安全门禁：响应全文不得含密钥明文
    assert "sk-deep-secret-9876" not in resp.text
    assert "sk-dash-secret-5432" not in resp.text


@pytest.mark.asyncio
async def test_get_llm_settings_empty_when_unconfigured(
    client: AsyncClient, override_db, auth_headers: dict[str, str]
) -> None:
    """未配置：密钥空串 + configured=False."""
    session = AsyncMock()
    session.execute.return_value = _result(None)
    override_db(session)

    resp = await client.get("/api/v1/settings/llm", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deepseek_api_key"] == ""
    assert data["dashscope_api_key"] == ""
    assert data["deepseek_configured"] is False
    assert data["dashscope_configured"] is False


# ── PUT /settings/llm（管理员）──


@pytest.mark.asyncio
async def test_put_llm_settings_encrypts_and_commits(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """管理员正常路径：密钥加密入库、显式 commit、审计留痕且 detail 不含密钥明文."""
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)
    plain_key = "sk-plain-secret-1234"

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "deepseek_api_key": plain_key,
            "dashscope_api_key": "",
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert session.committed is True

    # 行已加密入库
    row = session.row
    assert row is not None
    assert row.deepseek_api_key_enc != plain_key
    assert decrypt_secret(row.deepseek_api_key_enc) == plain_key
    assert row.dashscope_api_key_enc is None

    # 审计埋点：settings.llm_update，detail 只记字段名、无密钥明文
    audit_logs = [obj for obj in session.added if isinstance(obj, AuditLog)]
    assert len(audit_logs) == 1
    log = audit_logs[0]
    assert log.action == "settings.llm_update"
    detail_text = json.dumps(log.detail, ensure_ascii=False)
    assert plain_key not in detail_text
    assert "deepseek_api_key" in detail_text


@pytest.mark.asyncio
async def test_put_llm_settings_clears_with_empty_string(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """空串清除已有密钥（三态契约：""=清除）."""
    existing = _row(deepseek="sk-old-key", base="http://old/v1")
    session = _FakeSettingsSession(row=existing, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "deepseek_api_key": "",
            "dashscope_api_key": "",
            "embedding_api_base": "",
            "embedding_model": "",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 200
    assert existing.deepseek_api_key_enc is None
    assert existing.embedding_api_base is None


@pytest.mark.asyncio
async def test_put_llm_settings_omitted_keys_kept(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """三态契约（W-5）：省略密钥字段（None）→ 保持原密文不变."""
    existing = _row(deepseek="sk-keep-me", dashscope="sk-keep-2", base="http://emb/v1")
    before_deepseek = existing.deepseek_api_key_enc
    before_dashscope = existing.dashscope_api_key_enc
    session = _FakeSettingsSession(row=existing, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://emb/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 200
    assert existing.deepseek_api_key_enc == before_deepseek
    assert existing.dashscope_api_key_enc == before_dashscope


@pytest.mark.asyncio
async def test_put_llm_settings_requires_base_and_mock(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """全量契约：embedding_api_base/embedding_model/llm_mock 必填，缺失 → 422（密钥字段可省略）."""
    override_db(_FakeSettingsSession(user=_admin_user()))
    resp = await client.put(
        "/api/v1/settings/llm", headers=admin_headers, json={"deepseek_api_key": "sk-x"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_masked_key_rejected(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """S-1：疑似脱敏串（含连续 4 星号）服务端拒收 → 400 / code 4000."""
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "deepseek_api_key": "sk-****1234",
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000
    assert session.committed is False


@pytest.mark.asyncio
async def test_put_private_embedding_base_rejected(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """SSRF 防护：非 debug 下 embedding_api_base 指向私网 → 400 / code 4000."""
    monkeypatch_debug = settings.debug
    assert monkeypatch_debug is False  # 测试环境默认非 debug
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://192.168.1.10/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000
    assert session.committed is False


@pytest.mark.asyncio
async def test_put_invalidates_runtime_cache_only_after_commit(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """W-1 时序：commit 时缓存仍有效（未提前失效），commit 成功后才失效."""
    runtime._runtime_cache = (time.monotonic(), RuntimeLlmConfig())
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
        },
    )

    assert resp.status_code == 200
    assert session.committed is True
    assert session.cache_alive_at_commit is True  # commit 之前缓存仍有效
    assert runtime._runtime_cache is None  # commit 之后失效


# ── 自定义 LLM 端点（llm_model / llm_api_base）──


@pytest.mark.asyncio
async def test_put_custom_llm_model_and_base(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """新增大模型：llm_model + llm_api_base 入库（明文，非密钥）."""
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
            "llm_model": "qwen72b",
            "llm_api_base": "http://123.249.37.244:7778/v1",
        },
    )

    assert resp.status_code == 200
    row = session.row
    assert row is not None
    assert row.llm_model == "qwen72b"
    assert row.llm_api_base == "http://123.249.37.244:7778/v1"


@pytest.mark.asyncio
async def test_put_private_llm_base_rejected(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """SSRF 防护：llm_api_base 指向私网 → 400 / code 4000."""
    session = _FakeSettingsSession(row=None, user=_admin_user())
    override_db(session)

    resp = await client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "embedding_api_base": "http://emb:11434/v1",
            "embedding_model": "bge-m3",
            "llm_mock": False,
            "llm_model": "qwen72b",
            "llm_api_base": "http://10.0.0.5/v1",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000
    assert session.committed is False


@pytest.mark.asyncio
async def test_get_llm_settings_shows_custom_model(
    client: AsyncClient, override_db, auth_headers: dict[str, str]
) -> None:
    """GET 回显自定义模型与地址（明文）."""
    session = AsyncMock()
    session.execute.return_value = _result(
        LlmSetting(
            id=uuid.uuid4(),
            llm_model="qwen72b",
            llm_api_base="http://123.249.37.244:7778/v1",
            llm_mock=False,
        )
    )
    override_db(session)

    resp = await client.get("/api/v1/settings/llm", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["llm_model"] == "qwen72b"
    assert data["llm_api_base"] == "http://123.249.37.244:7778/v1"


@pytest.mark.asyncio
async def test_test_llm_custom_endpoint_without_key(
    client: AsyncClient,
    override_db,
    admin_headers: dict[str, str],
    fake_litellm,
    monkeypatch,
) -> None:
    """自定义端点（无 key）：acompletion 收到 openai/qwen72b、api_base 与 EMPTY 占位 key."""
    override_db(_admin_session_mock())
    _patch_cfg(
        monkeypatch,
        RuntimeLlmConfig(llm_model="qwen72b", llm_api_base="http://123.249.37.244:7778/v1"),
    )
    fake_litellm.acompletion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )
    )

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "llm"}
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["ok"] is True
    assert body["model"] == "openai/qwen72b"
    call_kwargs = fake_litellm.acompletion.call_args.kwargs
    assert call_kwargs["api_base"] == "http://123.249.37.244:7778/v1"
    assert call_kwargs["api_key"] == "EMPTY"


# ── POST /settings/llm/test（管理员）──


def _patch_cfg(monkeypatch, cfg: RuntimeLlmConfig | None) -> None:
    async def fake_get_runtime_config():
        return cfg

    # 运行时解析已迁至 runtime 子模块：打补丁目标须指向实际命名空间
    monkeypatch.setattr(runtime, "get_runtime_config", fake_get_runtime_config)


@pytest.mark.asyncio
async def test_test_llm_success(
    client: AsyncClient,
    override_db,
    admin_headers: dict[str, str],
    fake_litellm,
    monkeypatch,
) -> None:
    """target=llm：mock litellm 成功 → ok/model/latency_ms（HTTP 200 + code 0）."""
    override_db(_admin_session_mock())
    _patch_cfg(monkeypatch, RuntimeLlmConfig(deepseek_api_key="sk-ds"))
    fake_litellm.acompletion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )
    )

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "llm"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["ok"] is True
    assert body["data"]["model"] == settings.llm_primary
    assert isinstance(body["data"]["latency_ms"], int)


@pytest.mark.asyncio
async def test_test_llm_unconfigured(
    client: AsyncClient,
    override_db,
    admin_headers: dict[str, str],
    monkeypatch,
) -> None:
    """未配置密钥 → ok=false + 固定文案，HTTP 仍 200."""
    override_db(_admin_session_mock())
    _patch_cfg(monkeypatch, None)

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "llm"}
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == {"ok": False, "error": "未配置密钥或处于 mock 模式"}


@pytest.mark.asyncio
async def test_test_llm_exception_returns_ok_false_not_500(
    client: AsyncClient,
    override_db,
    admin_headers: dict[str, str],
    fake_litellm,
    monkeypatch,
) -> None:
    """异常全捕获：不抛 500，业务 ok=false."""
    override_db(_admin_session_mock())
    _patch_cfg(monkeypatch, RuntimeLlmConfig(deepseek_api_key="sk-bad"))
    fake_litellm.acompletion = AsyncMock(side_effect=RuntimeError("boom"))

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "llm"}
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is False
    assert data["error"]


@pytest.mark.asyncio
async def test_test_embedding_success(
    client: AsyncClient,
    override_db,
    admin_headers: dict[str, str],
    fake_litellm,
    monkeypatch,
) -> None:
    """target=embedding：mock aembedding 成功 → ok + dimension."""
    override_db(_admin_session_mock())
    _patch_cfg(monkeypatch, RuntimeLlmConfig())
    fake_litellm.aembedding = AsyncMock(
        return_value=SimpleNamespace(data=[{"embedding": [0.1] * 1024}])
    )

    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "embedding"}
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == {"ok": True, "dimension": 1024}


@pytest.mark.asyncio
async def test_test_invalid_target_returns_422(
    client: AsyncClient, override_db, admin_headers: dict[str, str]
) -> None:
    """target 仅允许 llm|embedding."""
    override_db(_admin_session_mock())
    resp = await client.post(
        "/api/v1/settings/llm/test", headers=admin_headers, json={"target": "other"}
    )
    assert resp.status_code == 422
