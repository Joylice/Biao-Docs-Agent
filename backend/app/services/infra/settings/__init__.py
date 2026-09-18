"""LLM 配置服务实现包 — 按职责域拆分自原 settings_service 单文件.

模块划分（依赖方向单向：security → runtime/storage → connectivity / providers）：
- ``security``：密钥脱敏、SSRF 防护、密文解密（纯函数，无共享状态）
- ``runtime``：运行时解析（库内优先/env 回退）、进程内缓存（_runtime_cache）、
  mock 判定、调用目标解析
- ``storage``：llm_settings 表 upsert 读写（加密入库/三态契约/变更字段清单）
- ``connectivity``：LLM/Embedding 连通性测试（litellm 调用，异常全捕获）
- ``providers``：Provider 注册表 + Model Route CRUD（参照 OpenMAIC）

门面 `app.services.infra.settings_service` 从本包 re-export 全部公共符号，
保持既有导入路径（``from app.services.infra import settings_service`` /
``from app.services.infra.settings_service import X``）完全兼容。
"""

from . import connectivity, providers, retrieval, runtime, security, storage

# connectivity
from .connectivity import (
    test_connection,
)

# providers
from .providers import (
    create_provider,
    delete_provider,
    list_providers,
    list_routes,
    update_provider,
    update_route,
)

# retrieval
from .retrieval import (
    get_retrieval_config_view,
    update_retrieval_config,
)

# runtime
from .runtime import (
    RuntimeLlmConfig,
    get_runtime_config,
    invalidate_runtime_cache,
    is_mock_enabled,
    resolve_llm_target,
)

# security
from .security import (
    mask_secret,
    validate_embedding_api_base,
    validate_llm_api_base,
)

# storage
from .storage import (
    get_llm_settings,
    get_settings_view,
    update_llm_settings,
)

# 缓存状态别名（供测试/门面直接引用；写入请用 runtime.invalidate_runtime_cache）
_runtime_cache = runtime._runtime_cache

__all__ = [
    "RuntimeLlmConfig",
    "connectivity",
    "create_provider",
    "delete_provider",
    "get_llm_settings",
    "get_retrieval_config_view",
    "get_runtime_config",
    "get_settings_view",
    "invalidate_runtime_cache",
    "is_mock_enabled",
    "list_providers",
    "list_routes",
    "mask_secret",
    "providers",
    "resolve_llm_target",
    "retrieval",
    "runtime",
    "security",
    "storage",
    "test_connection",
    "update_llm_settings",
    "update_provider",
    "update_retrieval_config",
    "update_route",
    "validate_embedding_api_base",
    "validate_llm_api_base",
]
