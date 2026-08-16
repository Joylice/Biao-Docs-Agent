"""settings_service 测试 — LLM 配置读写/脱敏/运行时解析/连通性测试（mock 会话，无真实 DB）.

说明（如实标注）：测试环境无 PostgreSQL，数据层经 MagicMock/AsyncMock 会话注入，
与 tests/unit/test_audit.py、tests/api/test_authorization.py 惯例一致。
"""

import sys
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.exceptions import ValidationError as BizValidationError
from app.models.llm_settings import LlmSetting
from app.schemas.settings import LlmSettingsUpdate
from app.services import settings_service
from app.services.settings_service import (
    RuntimeLlmConfig,
    get_runtime_config,
    get_settings_view,
    invalidate_runtime_cache,
    is_mock_enabled,
    mask_secret,
    update_llm_settings,
    validate_embedding_api_base,
)

# 别名导入：避免模块级 test_* 名称被 pytest 误收集为用例
run_connection_test = settings_service.test_connection


def _result(row: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _row(
    deepseek: str | None = None,
    dashscope: str | None = None,
    base: str | None = None,
    llm_mock: bool = False,
) -> LlmSetting:
    return LlmSetting(
        id=uuid.uuid4(),
        deepseek_api_key_enc=encrypt_secret(deepseek) if deepseek else None,
        dashscope_api_key_enc=encrypt_secret(dashscope) if dashscope else None,
        embedding_api_base=base,
        llm_mock=llm_mock,
    )


class _FakeSession:
    """upsert 假会话：execute 返回预设行，记录 add/flush."""

    def __init__(self, row: LlmSetting | None = None) -> None:
        self.row = row
        self.added: list = []
        self.flushed = False

    async def execute(self, stmt):
        return _result(self.row)

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, LlmSetting):
            self.row = obj

    async def flush(self) -> None:
        self.flushed = True


@pytest.fixture(autouse=True)
def _clean_runtime_cache():
    """每个用例前后清空运行时配置缓存，避免跨用例串扰."""
    invalidate_runtime_cache()
    yield
    invalidate_runtime_cache()


@pytest.fixture
def fake_litellm(monkeypatch):
    """注入假 litellm 模块（铁律：禁止真实调用 LLM）."""
    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


class TestLlmSettingModel:
    """llm_settings 表元数据."""

    def test_table_name_and_columns(self) -> None:
        assert LlmSetting.__tablename__ == "llm_settings"
        cols = LlmSetting.__table__.columns
        for name in (
            "id",
            "deepseek_api_key_enc",
            "dashscope_api_key_enc",
            "embedding_api_base",
            "llm_mock",
            "updated_at",
        ):
            assert name in cols, f"缺少列 {name}"

    def test_key_columns_nullable(self) -> None:
        """密钥/地址列可空（未配置 = NULL）."""
        assert LlmSetting.__table__.c.deepseek_api_key_enc.nullable is True
        assert LlmSetting.__table__.c.dashscope_api_key_enc.nullable is True
        assert LlmSetting.__table__.c.embedding_api_base.nullable is True


class TestMaskSecret:
    def test_mask_format(self) -> None:
        assert mask_secret("sk-1234567890abcd") == "sk-****abcd"

    def test_mask_empty(self) -> None:
        assert mask_secret("") == ""

    def test_mask_does_not_expose_full_key(self) -> None:
        masked = mask_secret("sk-1234567890abcd")
        assert "1234567890" not in masked


class TestGetSettingsView:
    """GET 视图：脱敏 + configured 标志."""

    async def test_view_when_no_row(self, monkeypatch) -> None:
        """未配置过：密钥为空串、configured=False，base/mock 展示 env 生效值."""
        monkeypatch.setattr(settings, "llm_mock", False)
        session = AsyncMock()
        session.execute.return_value = _result(None)

        view = await get_settings_view(session)

        assert view["deepseek_api_key"] == ""
        assert view["dashscope_api_key"] == ""
        assert view["deepseek_configured"] is False
        assert view["dashscope_configured"] is False
        assert view["embedding_api_base"] == settings.embedding_api_base
        assert view["llm_mock"] is False

    async def test_view_masks_configured_keys(self) -> None:
        """已配置：密钥脱敏为 sk-****后4位，configured=True."""
        session = AsyncMock()
        session.execute.return_value = _result(
            _row(deepseek="sk-deepseek1234", dashscope="sk-dash5678", base="http://emb:1/v1")
        )

        view = await get_settings_view(session)

        assert view["deepseek_api_key"] == "sk-****1234"
        assert view["dashscope_api_key"] == "sk-****5678"
        assert view["deepseek_configured"] is True
        assert view["dashscope_configured"] is True
        assert view["embedding_api_base"] == "http://emb:1/v1"
        # 安全门禁：视图任何字段不得含密钥明文
        assert "sk-deepseek1234" not in str(view)
        assert "sk-dash5678" not in str(view)

    async def test_view_partial_configured(self) -> None:
        """仅配置 deepseek：dashscope_configured=False."""
        session = AsyncMock()
        session.execute.return_value = _result(_row(deepseek="sk-only-deepseek"))

        view = await get_settings_view(session)

        assert view["deepseek_configured"] is True
        assert view["dashscope_configured"] is False
        assert view["dashscope_api_key"] == ""


class TestUpdateLlmSettings:
    """PUT upsert：密钥三态（None=保持/""=清除/非空=更新）、加密入库、变更字段清单."""

    def _payload(self, deepseek=None, dashscope=None, base="", llm_mock=False):
        return LlmSettingsUpdate(
            deepseek_api_key=deepseek,
            dashscope_api_key=dashscope,
            embedding_api_base=base,
            llm_mock=llm_mock,
        )

    async def test_creates_row_when_absent(self) -> None:
        """无行 → 新建，密钥加密入库（可解密还原）."""
        session = _FakeSession(row=None)

        changed = await update_llm_settings(
            session,
            self._payload(deepseek="sk-new-key", base="http://emb:2/v1", llm_mock=True),
        )

        assert session.flushed is True
        assert session.added and isinstance(session.added[0], LlmSetting)
        row = session.row
        assert row is not None
        assert row.deepseek_api_key_enc != "sk-new-key"  # 非明文
        assert decrypt_secret(row.deepseek_api_key_enc) == "sk-new-key"
        assert row.dashscope_api_key_enc is None  # 未提供 = 未配置
        assert row.embedding_api_base == "http://emb:2/v1"
        assert row.llm_mock is True
        assert set(changed) == {"deepseek_api_key", "embedding_api_base", "llm_mock"}

    async def test_empty_string_clears_key(self) -> None:
        """空串清除已有密钥（列置 NULL）."""
        existing = _row(deepseek="sk-old", dashscope="sk-old2", base="http://old/v1")
        session = _FakeSession(row=existing)

        changed = await update_llm_settings(session, self._payload(deepseek="", dashscope=""))

        assert existing.deepseek_api_key_enc is None
        assert existing.dashscope_api_key_enc is None
        assert existing.embedding_api_base is None
        assert set(changed) == {"deepseek_api_key", "dashscope_api_key", "embedding_api_base"}

    async def test_none_keeps_existing_keys(self) -> None:
        """W-5 三态：None（省略）→ 保持原密文不变，且不进 changed."""
        existing = _row(deepseek="sk-keep", dashscope="sk-keep2", base="http://emb/v1")
        before_deepseek = existing.deepseek_api_key_enc
        before_dashscope = existing.dashscope_api_key_enc
        session = _FakeSession(row=existing)

        changed = await update_llm_settings(session, self._payload(base="http://emb/v1"))

        assert existing.deepseek_api_key_enc == before_deepseek
        assert existing.dashscope_api_key_enc == before_dashscope
        assert decrypt_secret(existing.deepseek_api_key_enc) == "sk-keep"
        assert changed == []

    async def test_empty_clears_but_none_keeps_other(self) -> None:
        """混合三态：deepseek=""（清除）而 dashscope=None（保持）."""
        existing = _row(deepseek="sk-old", dashscope="sk-stay", base="http://emb/v1")
        before_dashscope = existing.dashscope_api_key_enc
        session = _FakeSession(row=existing)

        changed = await update_llm_settings(
            session, self._payload(deepseek="", base="http://emb/v1")
        )

        assert existing.deepseek_api_key_enc is None
        assert existing.dashscope_api_key_enc == before_dashscope
        assert changed == ["deepseek_api_key"]

    async def test_unchanged_values_not_in_changed(self) -> None:
        """重复提交相同值：changed 为空."""
        existing = _row(deepseek="sk-same", base="http://emb/v1", llm_mock=True)
        session = _FakeSession(row=existing)

        changed = await update_llm_settings(
            session,
            self._payload(deepseek="sk-same", base="http://emb/v1", llm_mock=True),
        )

        assert changed == []

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("deepseek", "sk-****1234"),
            ("dashscope", "sk-****abcd"),
            ("deepseek", "****"),
            ("dashscope", "abc_-****rest"),
        ],
    )
    async def test_masked_key_rejected(self, field: str, value: str) -> None:
        """S-1：含连续 4 星号的疑似脱敏串服务端拒收（业务错误 4000）."""
        session = _FakeSession(row=_row(deepseek="sk-real"))
        payload = (
            self._payload(deepseek=value) if field == "deepseek" else self._payload(dashscope=value)
        )

        with pytest.raises(BizValidationError) as exc:
            await update_llm_settings(session, payload)

        assert exc.value.code == 4000
        assert session.flushed is False

    async def test_update_does_not_invalidate_runtime_cache(self) -> None:
        """W-1：service 层不再内部失效缓存（移至 api 层 commit 成功后调用）."""
        settings_service._runtime_cache = (time.monotonic(), RuntimeLlmConfig())
        session = _FakeSession(row=None)

        await update_llm_settings(session, self._payload(deepseek="sk-x"))

        assert settings_service._runtime_cache is not None


class TestValidateEmbeddingApiBase:
    """SSRF 防护：私网/环回目标拒绝；debug 档放行 localhost/127.0.0.1."""

    @pytest.fixture(autouse=True)
    def _non_debug(self, monkeypatch):
        monkeypatch.setattr(settings, "debug", False)

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.5/v1",
            "http://172.16.1.1/v1",
            "http://192.168.1.10/v1",
            "http://127.0.0.1:11434/v1",
            "http://169.254.1.1/v1",
            "http://0.0.0.0/v1",
            "http://[::1]/v1",
            "http://localhost:11434/v1",
        ],
    )
    def test_non_debug_rejects_private_and_local(self, url: str) -> None:
        with pytest.raises(BizValidationError) as exc:
            validate_embedding_api_base(url)
        assert exc.value.code == 4000

    def test_non_debug_allows_public_https(self) -> None:
        validate_embedding_api_base("https://api.openai.com/v1")

    def test_non_debug_allows_public_ip(self) -> None:
        validate_embedding_api_base("http://8.8.8.8:11434/v1")

    def test_non_http_scheme_rejected(self) -> None:
        with pytest.raises(BizValidationError):
            validate_embedding_api_base("ftp://1.2.3.4/v1")

    def test_invalid_url_rejected(self) -> None:
        with pytest.raises(BizValidationError):
            validate_embedding_api_base("not a url")

    def test_debug_allows_localhost_and_loopback(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "debug", True)
        validate_embedding_api_base("http://localhost:11434/v1")
        validate_embedding_api_base("http://127.0.0.1:11434/v1")
        validate_embedding_api_base("http://[::1]:11434/v1")

    def test_debug_still_rejects_private(self, monkeypatch) -> None:
        """debug 档仅放行 loopback，其余私网段仍拒绝."""
        monkeypatch.setattr(settings, "debug", True)
        with pytest.raises(BizValidationError):
            validate_embedding_api_base("http://10.0.0.5/v1")

    async def test_upsert_rejects_private_base(self, monkeypatch) -> None:
        """PUT 路径集成：upsert 对非空 base 执行 SSRF 校验."""
        monkeypatch.setattr(settings, "debug", False)
        session = _FakeSession(row=None)
        payload = LlmSettingsUpdate(embedding_api_base="http://localhost:11434/v1", llm_mock=False)
        with pytest.raises(BizValidationError):
            await update_llm_settings(session, payload)
        assert session.flushed is False


class TestRuntimeLlmConfig:
    def test_api_key_for_deepseek_prefix(self) -> None:
        cfg = RuntimeLlmConfig(deepseek_api_key="sk-ds", dashscope_api_key="sk-qw")
        assert cfg.api_key_for("deepseek/deepseek-chat") == "sk-ds"

    def test_api_key_for_qwen_prefix(self) -> None:
        cfg = RuntimeLlmConfig(deepseek_api_key="sk-ds", dashscope_api_key="sk-qw")
        assert cfg.api_key_for("qwen/qwen-plus") == "sk-qw"

    def test_api_key_for_unknown_prefix(self) -> None:
        cfg = RuntimeLlmConfig(deepseek_api_key="sk-ds")
        assert cfg.api_key_for("gpt-4o") is None


class TestGetRuntimeConfig:
    """运行时配置解析：库内优先、缓存、DB 失败回退."""

    async def test_reads_row_from_db(self, monkeypatch) -> None:
        session = AsyncMock()
        session.execute.return_value = _result(
            _row(deepseek="sk-ds", dashscope="sk-qw", base="http://emb:9/v1", llm_mock=True)
        )

        @asynccontextmanager
        async def fake_factory():
            yield session

        monkeypatch.setattr(settings_service, "async_session_factory", fake_factory)

        cfg = await get_runtime_config()

        assert cfg is not None
        assert cfg.deepseek_api_key == "sk-ds"
        assert cfg.dashscope_api_key == "sk-qw"
        assert cfg.embedding_api_base == "http://emb:9/v1"
        assert cfg.llm_mock is True

    async def test_no_row_returns_none(self, monkeypatch) -> None:
        session = AsyncMock()
        session.execute.return_value = _result(None)

        @asynccontextmanager
        async def fake_factory():
            yield session

        monkeypatch.setattr(settings_service, "async_session_factory", fake_factory)
        assert await get_runtime_config() is None

    async def test_cached_within_ttl(self, monkeypatch) -> None:
        """TTL 内命中缓存：会话工厂只被调用一次."""
        calls = {"n": 0}
        session = AsyncMock()
        session.execute.return_value = _result(_row(deepseek="sk-ds"))

        @asynccontextmanager
        async def fake_factory():
            calls["n"] += 1
            yield session

        monkeypatch.setattr(settings_service, "async_session_factory", fake_factory)

        await get_runtime_config()
        await get_runtime_config()

        assert calls["n"] == 1

    async def test_db_failure_falls_back_to_none(self):
        """DB 不可达（测试环境无 PostgreSQL）：捕获异常回退 None，不抛错."""
        invalidate_runtime_cache()
        cfg = await get_runtime_config()
        assert cfg is None


class TestIsMockEnabled:
    """mock 判定：显式参数 > env ∨ 库内开关（任一为 true 即 mock）."""

    async def test_explicit_param_wins(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", True)
        assert await is_mock_enabled(False) is False
        monkeypatch.setattr(settings, "llm_mock", False)
        assert await is_mock_enabled(True) is True

    async def test_env_mock_true(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", True)
        assert await is_mock_enabled(None) is True

    async def test_db_mock_true(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", False)

        async def fake_cfg():
            return RuntimeLlmConfig(llm_mock=True)

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)
        assert await is_mock_enabled(None) is True

    async def test_both_false(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", False)

        async def fake_cfg():
            return RuntimeLlmConfig(llm_mock=False)

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)
        assert await is_mock_enabled(None) is False


class TestConnection:
    """POST /settings/llm/test 服务层（litellm 全 mock）."""

    async def test_llm_unconfigured_returns_not_configured(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", False)

        async def fake_cfg():
            return None

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)
        result = await run_connection_test("llm")
        assert result == {"ok": False, "error": "未配置密钥或处于 mock 模式"}

    async def test_llm_mock_mode_returns_not_configured(self, fake_litellm, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", True)
        result = await run_connection_test("llm")
        assert result == {"ok": False, "error": "未配置密钥或处于 mock 模式"}
        fake_litellm.acompletion.assert_not_called()

    async def test_llm_success(self, fake_litellm, monkeypatch) -> None:
        """真实调用路径（mock litellm）：返回 ok/model/latency_ms，密钥作为 api_key 传入."""
        monkeypatch.setattr(settings, "llm_mock", False)
        fake_litellm.acompletion = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
            )
        )

        async def fake_cfg():
            return RuntimeLlmConfig(deepseek_api_key="sk-ds-test")

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)

        result = await run_connection_test("llm")

        assert result["ok"] is True
        assert result["model"] == settings.llm_primary
        assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0
        kwargs = fake_litellm.acompletion.call_args.kwargs
        assert kwargs["api_key"] == "sk-ds-test"
        assert kwargs["max_tokens"] == 8
        assert kwargs["messages"] == [{"role": "user", "content": "ping"}]

    async def test_llm_failure_returns_ok_false_not_raise(self, fake_litellm, monkeypatch) -> None:
        """调用异常：业务 ok=false + 简短原因，不抛出."""
        monkeypatch.setattr(settings, "llm_mock", False)
        fake_litellm.acompletion = AsyncMock(side_effect=RuntimeError("auth failed"))

        async def fake_cfg():
            return RuntimeLlmConfig(deepseek_api_key="sk-bad")

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)

        result = await run_connection_test("llm")

        assert result["ok"] is False
        assert result["error"]
        assert "auth failed" in result["error"]

    async def test_embedding_success(self, fake_litellm, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", False)
        fake_litellm.aembedding = AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2, 0.3, 0.4]}])
        )

        async def fake_cfg():
            return RuntimeLlmConfig(embedding_api_base="http://emb:1/v1")

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)

        result = await run_connection_test("embedding")

        assert result == {"ok": True, "dimension": 4}
        kwargs = fake_litellm.aembedding.call_args.kwargs
        assert kwargs["api_base"] == "http://emb:1/v1"
        assert kwargs["input"] == ["测试"]

    async def test_embedding_mock_mode_returns_not_configured(
        self, fake_litellm, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "llm_mock", True)
        result = await run_connection_test("embedding")
        assert result == {"ok": False, "error": "未配置密钥或处于 mock 模式"}
        fake_litellm.aembedding.assert_not_called()

    async def test_embedding_failure_returns_ok_false(self, fake_litellm, monkeypatch) -> None:
        monkeypatch.setattr(settings, "llm_mock", False)
        fake_litellm.aembedding = AsyncMock(side_effect=ConnectionError("conn refused"))

        async def fake_cfg():
            return None

        monkeypatch.setattr(settings_service, "get_runtime_config", fake_cfg)

        result = await run_connection_test("embedding")

        assert result["ok"] is False
        assert "conn refused" in result["error"]
