"""Skill Schema — /settings/skills 请求体（S4）.

与 `external_tools.py` 的关键差异：**无 admin 门禁**。skill 是「我的行为准则」
这种用户级资产，普通用户即可维护（产品口径②B「用户层全员共享」）；
外部工具配的是全局密钥，必须 admin。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class SkillCreate(BaseModel):
    """POST /settings/skills 请求.

    ``created_by`` 不由前端指定 —— 一律服务端固定 "user"（人工创建即启用）。
    "llm" 来源只会从 Agent Runtime 的 ``create_skill`` 工具进入（默认 enabled=False 待人审）。
    """

    name: str = Field(description="小写字母开头，仅小写字母/数字/下划线，3~64 字符")
    title: str = Field(description="展示名")
    description: str = Field(description="选择契约（供未来自动路由使用）")
    stage_key: str = Field(description="所属阶段 ∈ VALID_STAGE_KEYS")
    body_md: str = Field(description="行为准则正文，≤ SKILL_BODY_MAX_CHARS")
    agent_id: str | None = Field(default=None, description="绑定的 Agent（多 Agent 阶段用）")
    metadata: dict[str, Any] | None = None


class SkillUpdate(BaseModel):
    """PUT /settings/skills/{name} 请求（三态 + 乐观锁）.

    三态语义对齐 ``tools_service``：``None`` = 保持原值。
    """

    title: str | None = None
    description: str | None = None
    body_md: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None
    expected_version: int | None = Field(default=None, description="乐观锁版本号；不匹配 → 409")


class SkillPreviewBody(BaseModel):
    """POST /settings/skills/preview 请求 —— 预览渲染结果，不落库.

    ``name`` 为空时按「草稿」处理（用 body_md 直接造契约，不查注册表），
    便于用户在编辑器里改到一半就想看最终提示词。
    """

    name: str | None = None
    body_md: str
    stage_key: str | None = None
    title: str | None = None
    description: str | None = None
    context: dict[str, Any] = Field(
        default_factory=dict, description="数据注入上下文（与 compose context 同构）"
    )


class SkillImportResult(BaseModel):
    """POST /settings/skills/import 的返回项."""

    name: str
    created: bool
    message: str


class SkillExportQuery(BaseModel):
    """GET /settings/skills/export 查询参数（仅作文档用途，实际用 Query 声明）."""

    include_builtin: bool = False
    names: list[str] | None = None


class SkillOwnerRef(BaseModel):
    """owner 引用（当前仅作创建者标记，全员共享，不过滤）."""

    owner_id: uuid.UUID | None = None


__all__ = [
    "SkillCreate",
    "SkillExportQuery",
    "SkillImportResult",
    "SkillOwnerRef",
    "SkillPreviewBody",
    "SkillUpdate",
]
