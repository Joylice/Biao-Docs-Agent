"""外部工具 Schema — Phase 2 工具与技能页面 API 请求体."""

from pydantic import BaseModel


class ToolCreate(BaseModel):
    """POST /settings/external-tools 请求."""

    name: str
    preset: str = "custom"
    tool_type: str = "http_search"
    api_key: str | None = None
    base_url: str | None = None
    timeout_ms: int = 10000
    max_query_chars: int = 400
    enabled: bool = True


class ToolUpdate(BaseModel):
    """PUT /settings/external-tools/{id} 请求 — 密钥三态 + 乐观锁.

    - api_key: None=保持、""=清除、非空=更新
    - base_url: None=保持、""=清除、非空=更新+SSRF 校验
    - expected_version: 乐观锁版本号（必传，与 DB 中 version 不匹配 → 409）
    """

    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout_ms: int | None = None
    max_query_chars: int | None = None
    enabled: bool | None = None
    expected_version: int


class BindBody(BaseModel):
    """PUT /settings/external-tools/{id}/bind 请求."""

    stage_key: str
