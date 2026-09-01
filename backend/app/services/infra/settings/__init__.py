"""LLM 配置服务实现包 — 按职责域拆分自原 settings_service 单文件.

模块划分（依赖方向单向：security → runtime/storage → connectivity）：
- ``security``：密钥脱敏、SSRF 防护、密文解密（纯函数，无共享状态）
- ``runtime``：运行时解析（库内优先/env 回退）、进程内缓存（_runtime_cache）、
  mock 判定、调用目标解析
- ``storage``：llm_settings 表 upsert 读写（加密入库/三态契约/变更字段清单）
- ``connectivity``：LLM/Embedding 连通性测试（litellm 调用，异常全捕获）

门面 `app.services.infra.settings_service` 从本包 re-export 全部公共符号，
保持既有导入路径（``from app.services.infra import settings_service`` /
``from app.services.infra.settings_service import X``）完全兼容。
"""

from . import security
from . import runtime
from . import storage
from . import connectivity

# security
from .security import (
    mask_secret,
    validate_embedding_api_base,
    validate_llm_api_base,
)

# runtime
from .runtime import (
    RuntimeLlmConfig,
    get_runtime_config,
    invalidate_runtime_cache,
    is_mock_enabled,
    resolve_llm_target,
)

# storage
from .storage import (
    get_llm_settings,
    get_settings_view,
    update_llm_settings,
)

# connectivity
from .connectivity import (
    test_connection,
)

# 缓存状态别名（供测试/门面直接引用；写入请用 runtime.invalidate_runtime_cache）
_runtime_cache = runtime._runtime_cache

__all__ = [
    # security
    "mask_secret",
    "validate_embedding_api_base",
    "validate_llm_api_base",
    # runtime
    "RuntimeLlmConfig",
    "get_runtime_config",
    "invalidate_runtime_cache",
    "is_mock_enabled",
    "resolve_llm_target",
    # storage
    "get_llm_settings",
    "get_settings_view",
    "update_llm_settings",
    # connectivity
    "test_connection",
    # 子模块
    "security",
    "runtime",
    "storage",
    "connectivity",
]
