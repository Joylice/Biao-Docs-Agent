"""LLM 配置服务门面（facade）— 动态转发至 settings 包子模块.

**实现位置**：逻辑已按职责域拆分至 ``app.services.infra.settings`` 包
（security / runtime / storage / connectivity 四个子模块），本文件仅做转发。

采用 **PEP 562 模块级 ``__getattr__`` 动态转发**（而非静态 re-export）：
- 保持两种导入路径完全兼容：
  ``from app.services.infra import settings_service`` /
  ``from app.services.infra.settings_service import RuntimeLlmConfig, ...``；
- 动态解析到**子模块命名空间**（而非包 __init__ 的静态绑定），保证 monkeypatch
  （打补丁到 runtime/storage 等实际实现模块）**实时生效**（第一轮拆分实测教训）。

运行时生效策略（选型说明，详见 runtime 子模块）：
- ``get_runtime_config()`` 带 **30s TTL 进程内缓存**，DB 不可达时 5s 负缓存。
- 缓存失效由 **api 层在 commit 成功之后** 调用 ``invalidate_runtime_cache()``
  （W-1：避免事务未提交即失效导致读到旧值）；跨进程（arq worker）靠 TTL 过期收敛。
"""

from app.services.infra import settings as _impl

# 公共符号 → 所在子模块（动态转发目标）
_SYMBOL_SOURCE: dict[str, str] = {
    # security
    "mask_secret": "security",
    "validate_embedding_api_base": "security",
    "validate_llm_api_base": "security",
    # runtime
    "RuntimeLlmConfig": "runtime",
    "get_runtime_config": "runtime",
    "invalidate_runtime_cache": "runtime",
    "is_mock_enabled": "runtime",
    "resolve_llm_target": "runtime",
    # storage
    "get_llm_settings": "storage",
    "get_settings_view": "storage",
    "update_llm_settings": "storage",
    # connectivity
    "test_connection": "connectivity",
}

__all__ = list(_SYMBOL_SOURCE)


def __getattr__(name: str):
    """动态转发公共符号到对应子模块（PEP 562）."""
    source = _SYMBOL_SOURCE.get(name)
    if source is not None:
        return getattr(getattr(_impl, source), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
