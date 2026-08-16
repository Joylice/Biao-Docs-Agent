"""LLM 配置页面化 Schema."""

from typing import Literal

from pydantic import BaseModel


class LlmSettingsUpdate(BaseModel):
    """PUT /settings/llm 请求 — 密钥字段三态契约（W-5）：

    - None（省略字段）= 保持原值不变
    - ""（空字符串）= 清除该项
    - 非空 = 更新（服务端拒收疑似脱敏串，S-1）

    embedding_api_base / llm_mock 保持必填全量（"" = 清除 base 回退 env）。
    """

    deepseek_api_key: str | None = None
    dashscope_api_key: str | None = None
    embedding_api_base: str
    llm_mock: bool


class LlmSettingsTestRequest(BaseModel):
    """POST /settings/llm/test 请求."""

    target: Literal["llm", "embedding"]
