"""Skill 用户层 CRUD 服务 — 乐观锁 + 门禁 + 缓存失效.

对齐 `infra/tools/tools_service.py` 的范式（三态字段/乐观锁/幂等），
但**门禁口径不同**：外部工具配的是全局密钥（必须 admin），
skill 是「行为准则」这种用户级资产，普通用户即可维护自己的（见产品口径②B）。

安全门禁（`create_skill` 是最强能力，必须设闸）：
1. name 白名单正则（防路径穿越，zip 导入场景同源风险）；
2. **不得与内置 skill 同名** —— 防用户覆盖系统准则；
3. name 在用户层唯一（DB 约束 + 前置友好校验）；
4. body 长度 ≤ SKILL_BODY_MAX_CHARS（token 预算保护）；
5. stage_key ∈ VALID_STAGE_KEYS；
6. LLM 自建（created_by="llm"）默认 enabled=False，待人审启用。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.user_skill import UserSkill
from app.services.skills import registry
from app.services.skills.contract import (
    SKILL_BODY_MAX_CHARS,
    SKILL_NAME_PATTERN,
    SkillContract,
)
from app.services.skills.loader import load_builtin_skills

logger = logging.getLogger(__name__)


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not SKILL_NAME_PATTERN.match(name):
        raise ValidationError(
            f"skill 名称 '{name}' 非法：须为小写字母开头，仅含小写字母/数字/下划线，3~64 字符"
        )
    return name


def _validate_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise ValidationError("行为准则正文不可为空")
    if len(body) > SKILL_BODY_MAX_CHARS:
        raise ValidationError(
            f"行为准则正文超限：{len(body)} 字符 > {SKILL_BODY_MAX_CHARS}（提示词 token 预算保护）"
        )
    return body


def _reject_builtin_shadow(name: str) -> None:
    """拒绝与内置 skill 同名 —— 防用户覆盖系统准则.

    覆盖内置是**内置层的能力**（改 backend/skills/ 文件），不应由用户在运行期做。
    注意 registry 里还有一层兜底（针对 user-invocable=false 的内置），
    本处是最前置的友好校验（早失败 + 文案清晰）。
    """
    if name in load_builtin_skills():
        raise ConflictError(f"'{name}' 与内置准则同名，不可覆盖；请另取名称")


async def create_skill(
    db: AsyncSession,
    *,
    name: str,
    title: str,
    description: str,
    stage_key: str,
    body_md: str,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    owner_id: uuid.UUID | None = None,
    created_by: str = "user",
) -> UserSkill:
    """创建用户级 skill.

    ``created_by="llm"`` 时默认 ``enabled=False``（产品口径①A：待人审启用），
    人工创建（"user"）直接启用。
    """
    name = _validate_name(name)
    body_md = _validate_body(body_md)

    if not title or not title.strip():
        raise ValidationError("标题不可为空")
    if not description or not description.strip():
        raise ValidationError("描述不可为空（选择契约，供未来自动路由使用）")
    if stage_key not in registry.VALID_STAGE_KEYS:
        raise ValidationError(f"阶段 '{stage_key}' 非法，须 ∈ {sorted(registry.VALID_STAGE_KEYS)}")

    _reject_builtin_shadow(name)

    exists = await db.execute(select(UserSkill).where(UserSkill.name == name))
    if exists.scalar_one_or_none() is not None:
        raise ConflictError(f"skill '{name}' 已存在")

    is_llm = created_by == "llm"
    row = UserSkill(
        name=name,
        title=title.strip(),
        description=description.strip(),
        stage_key=stage_key,
        agent_id=agent_id,
        body_md=body_md,
        metadata_json=metadata or {},
        # ①A：LLM 自建默认禁用，待人审
        enabled=not is_llm,
        created_by="llm" if is_llm else "user",
        owner_id=owner_id,
        version=1,
    )
    db.add(row)
    await db.flush()
    registry.invalidate()
    logger.info(
        "skill 已创建: name=%s stage=%s created_by=%s enabled=%s",
        name,
        stage_key,
        row.created_by,
        row.enabled,
    )
    return row


async def update_skill(
    db: AsyncSession,
    name: str,
    *,
    title: str | None = None,
    description: str | None = None,
    body_md: str | None = None,
    enabled: bool | None = None,
    metadata: dict[str, Any] | None = None,
    expected_version: int | None = None,
) -> UserSkill:
    """更新用户级 skill（乐观锁）.

    三态语义：``None`` = 保持原值（对齐 tools_service 的密钥三态处理思路）。
    """
    row = await get_skill(db, name)

    if expected_version is not None and row.version != expected_version:
        raise ConflictError("该准则已被其他操作修改，请刷新后重试")

    if title is not None:
        if not title.strip():
            raise ValidationError("标题不可为空")
        row.title = title.strip()
    if description is not None:
        if not description.strip():
            raise ValidationError("描述不可为空")
        row.description = description.strip()
    if body_md is not None:
        row.body_md = _validate_body(body_md)
    if enabled is not None:
        row.enabled = bool(enabled)
    if metadata is not None:
        row.metadata_json = metadata

    row.version += 1
    await db.flush()
    registry.invalidate()
    logger.info("skill 已更新: name=%s version=%s enabled=%s", name, row.version, row.enabled)
    return row


async def delete_skill(db: AsyncSession, name: str) -> None:
    """删除用户级 skill（删除后回退内置层，若有同名内置）."""
    row = await get_skill(db, name)
    await db.delete(row)
    await db.flush()
    registry.invalidate()
    logger.info("skill 已删除: name=%s", name)


async def reset_skill(db: AsyncSession, name: str) -> None:
    """「恢复内置」= 删除用户层覆盖（无内置同名时等同删除）."""
    await delete_skill(db, name)


async def get_skill(db: AsyncSession, name: str) -> UserSkill:
    """按 name 取用户层记录，未命中抛 NotFoundError."""
    result = await db.execute(select(UserSkill).where(UserSkill.name == name))
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"用户级准则 '{name}' 不存在")
    return row


async def list_skill_rows(db: AsyncSession) -> list[UserSkill]:
    """列出全部用户层记录（含 disabled —— 管理视图需要看到待审项）."""
    result = await db.execute(select(UserSkill).order_by(UserSkill.name))
    return list(result.scalars().all())


def row_to_view(row: UserSkill) -> dict[str, Any]:
    """ORM → API 视图（含来源层与虚拟路径，便于前端区分内置/用户）."""
    contract = SkillContract(
        name=row.name,
        title=row.title,
        description=row.description or "",
        version=row.skill_version,
        stage_key=row.stage_key,
        body=row.body_md,
        agent_id=row.agent_id,
        metadata=row.metadata_json or {},
        builtin=False,
        db_id=str(row.id),
        db_version=row.version,
    )
    return {
        "name": row.name,
        "title": row.title,
        "description": row.description or "",
        "version": row.skill_version,
        "stageKey": row.stage_key,
        "agentId": row.agent_id,
        "bodyMd": row.body_md,
        "metadata": row.metadata_json or {},
        "enabled": row.enabled,
        "createdBy": row.created_by,
        "optimisticVersion": row.version,
        "builtin": False,
        "virtualPath": contract.virtual_path,
        "shadowsBuiltin": row.name in load_builtin_skills(),
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def contract_to_view(c: SkillContract, *, editable: bool) -> dict[str, Any]:
    """SkillContract → API 视图（内置层用）."""
    return {
        "name": c.name,
        "title": c.title,
        "description": c.description,
        "version": c.version,
        "stageKey": c.stage_key,
        "agentId": c.agent_id,
        "bodyMd": c.body,
        "metadata": c.metadata,
        "enabled": True,
        "createdBy": "builtin",
        "optimisticVersion": None,
        "builtin": True,
        "virtualPath": c.virtual_path,
        "editable": editable,
        "updatedAt": None,
    }


__all__ = [
    "SKILL_BODY_MAX_CHARS",
    "contract_to_view",
    "create_skill",
    "delete_skill",
    "get_skill",
    "list_skill_rows",
    "reset_skill",
    "row_to_view",
    "update_skill",
]
