"""LLM 配置页面化 Schema."""

from typing import Literal

from pydantic import BaseModel


class LlmSettingsUpdate(BaseModel):
    """PUT /settings/llm 请求 — 密钥字段三态契约（W-5）：

    - None（省略字段）= 保持原值不变
    - ""（空字符串）= 清除该项
    - 非空 = 更新（服务端拒收疑似脱敏串，S-1）

    embedding_api_base / embedding_model / llm_mock 保持必填全量（"" = 清除 base/model 回退 env）。
    embedding_api_key 走密钥三态（与 deepseek/dashscope 一致）。
    """

    deepseek_api_key: str | None = None
    dashscope_api_key: str | None = None
    # 主流云端厂商密钥（三态：None=保持原值、""=清除、非空=更新）
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    zhipu_api_key: str | None = None
    moonshot_api_key: str | None = None
    # 自定义 LLM 主模型、服务地址与端点专用密钥
    # （可选，与密钥同三态：None=保持原值、""=清除、非空=更新）
    llm_model: str | None = None
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    embedding_api_base: str
    embedding_model: str
    embedding_api_key: str | None = None
    llm_mock: bool


class LlmSettingsTestRequest(BaseModel):
    """POST /settings/llm/test 请求.

    model/api_base/api_key 为可选覆盖：携带时按表单未保存的值测试
    （「先测试再保存」流程）；api_key 缺省时回退已保存的端点专用密钥。
    """

    target: Literal["llm", "embedding"]
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None


# === Provider Registry Schemas ===


class ProviderCreate(BaseModel):
    """POST /settings/providers 请求."""

    name: str
    prefix: str
    api_key: str | None = None
    api_base: str | None = None
    capabilities: list[str] = []  # text/embedding/rerank/vision
    models: str | None = None


class ProviderUpdate(BaseModel):
    """PUT /settings/providers/{id} 请求 — 密钥三态."""

    name: str | None = None
    api_key: str | None = None  # 三态：None=保持、""=清除、非空=更新
    api_base: str | None = None
    enabled: bool | None = None
    capabilities: list[str] | None = None
    models: str | None = None


class RouteUpdate(BaseModel):
    """PUT /settings/routes/{stage_key} 请求."""

    model: str | None = None
    fallback: list[str] | None = None
    thinking: bool | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    hint: str | None = None
    enabled: bool | None = None


class RouteBatchUpdate(BaseModel):
    """PUT /settings/routes 请求 — 批量更新路由."""

    routes: list[RouteUpdate]


# === Retrieval Config Schemas ===


class RetrievalConfigUpdate(BaseModel):
    """PUT /settings/retrieval 请求 — 检索参数更新.

    rerank_api_key 走密钥三态（None=保持、""=清除、非空=更新）。
    其余字段为全量必填（非 None 时更新）。
    """

    recall_top_k: int | None = None
    similarity_threshold: float | None = None
    hybrid_weight: float | None = None
    rerank_enabled: bool | None = None
    rerank_model: str | None = None
    rerank_top_k: int | None = None
    rerank_api_key: str | None = None  # 三态
