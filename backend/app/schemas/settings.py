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
    # 自定义 LLM 主模型、服务地址与端点专用密钥（可选，与密钥同三态：None=保持原值、""=清除、非空=更新）
    llm_model: str | None = None
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    embedding_api_base: str
    embedding_model: str
    embedding_api_key: str | None = None
    llm_mock: bool


class LlmSettingsTestRequest(BaseModel):
    """POST /settings/llm/test 请求."""

    target: Literal["llm", "embedding"]
