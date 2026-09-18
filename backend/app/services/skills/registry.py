"""Skill 注册表 — listSkills 双源合并（内置文件系统 + 用户 DB）.

对齐 OpenMAIC 的 `listSkills(ownerId)` 语义，但按本项目产品口径做了两处收敛：

1. **无虚拟文件系统**：内置层是真实文件（`backend/skills/*/SKILL.md`），
   用户层在 DB。两层的「路径」概念由 `SkillContract.virtual_path` 表达
   （`/__builtin_skills__/<name>/SKILL.md` vs `/__user_skills__/<name>/SKILL.md`），
   仅用于日志/报错/导出还原，不引入真实挂载。
2. **owner 不做隔离**（产品口径②B「用户层全员共享」）：
   `list_skills` 接收 `owner_id` 但**不据此过滤**，该参数保留给未来可能的隔离需求；
   `UserSkill.owner_id` 仅作创建者标记。

合并规则：**同名时用户层覆盖内置层**（用户可覆盖系统准则）；
`enabled=False` 的用户 skill 视为不存在（回退内置层）—— LLM 自建的 skill 默认 False 待人审。
"""

from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_skill import UserSkill
from app.services.skills.contract import SkillContract, SkillContractError, validate_contract
from app.services.skills.loader import load_builtin_skills

logger = logging.getLogger(__name__)

# 用户层缓存 TTL（对齐 infra/tools/registry.py 的 30s 范式）
_CACHE_TTL = 30.0
_user_cache: dict[str, tuple[float, dict[str, SkillContract]]] = {}

# 合法 stage_key（与后端 STAGE_KEYS 8 项对齐）
VALID_STAGE_KEYS = {
    "parse",
    "score",
    "outline",
    "write",
    "validate",
    "consistency",
    "review",
    "export",
}


def _user_skill_to_contract(row: UserSkill) -> SkillContract:
    """ORM 行 → SkillContract（builtin=False）."""
    return SkillContract(
        name=row.name,
        title=row.title,
        description=row.description or "",
        version=row.skill_version,
        stage_key=row.stage_key,
        body=row.body_md,
        user_invocable=True,
        agent_id=row.agent_id,
        metadata=row.metadata_json or {},
        builtin=False,
        source_path=None,
        db_id=str(row.id),
        db_version=row.version,
    )


async def load_user_skills(db: AsyncSession, *, force: bool = False) -> dict[str, SkillContract]:
    """读用户层（带 TTL 缓存）.

    只取 `enabled=True` 的行 —— 禁用的 skill 等同于不存在（回退内置层）。
    单行契约非法（如 name 不合法）时**跳过该行**并记 error，不阻断整体。
    """
    cache_key = "all"
    now = time.monotonic()
    hit = _user_cache.get(cache_key)
    if not force and hit is not None and now - hit[0] < _CACHE_TTL:
        return hit[1]

    result = await db.execute(select(UserSkill).where(UserSkill.enabled.is_(True)))
    skills: dict[str, SkillContract] = {}
    for row in result.scalars().all():
        try:
            contract = _user_skill_to_contract(row)
            validate_contract(contract, valid_stage_keys=VALID_STAGE_KEYS)
        except SkillContractError as e:
            logger.error("用户 skill 契约非法，已跳过: %s（%s）", row.name, e)
            continue
        skills[contract.name] = contract

    _user_cache[cache_key] = (now, skills)
    return skills


async def list_skills(
    db: AsyncSession | None = None,
    owner_id: uuid.UUID | str | None = None,
) -> list[SkillContract]:
    """合并两层 → 全量 skill 注册表（对齐 OpenMAIC listSkills）.

    Args:
        db: DB session；为 None 时**只返回内置层**（无 DB 的降级路径，如单测/离线）。
        owner_id: 保留参数（按产品口径「用户层全员共享」，当前**不过滤**）。

    Returns:
        按 name 升序的合并结果；同名时用户层覆盖内置层。
    """
    builtin = load_builtin_skills()
    merged: dict[str, SkillContract] = dict(builtin)

    if db is not None:
        user_skills = await load_user_skills(db)
        # 同名覆盖，但 **user-invocable=False 的内置 skill 不可被覆盖** ——
        # 契约层「本 skill 的行为由系统固化」的表达，靠这里兜底（不靠 service 单点门禁，
        # 因为存量行 / 直接写库都能绕过 service）。
        blocked = [n for n in user_skills if n in builtin and not builtin[n].user_invocable]
        if blocked:
            logger.warning(
                "以下用户 skill 试图覆盖 user-invocable=false 的内置准则，已拒绝: %s", blocked
            )
        merged.update({k: v for k, v in user_skills.items() if k not in blocked})
    else:
        logger.debug("list_skills 未传 db，仅返回内置层（owner_id=%s）", owner_id)

    return sorted(merged.values(), key=lambda c: c.name)


async def find_skill(
    name: str,
    db: AsyncSession | None = None,
    owner_id: uuid.UUID | str | None = None,
) -> SkillContract | None:
    """按 name 查单个 skill（用户层优先，未命中回退内置层）.

    这是 Agent Runtime「按需消费」的核心入口。
    与 `list_skills` 共用同一套覆盖规则（含 user-invocable 门禁）。
    """
    if db is not None:
        user_skills = await load_user_skills(db)
        if name in user_skills:
            builtin = load_builtin_skills()
            b = builtin.get(name)
            if b is not None and not b.user_invocable:
                logger.warning(
                    "用户 skill '%s' 试图覆盖 user-invocable=false 的内置准则，已回退内置", name
                )
                return b
            return user_skills[name]
    return load_builtin_skills().get(name)


async def find_skill_for_agent(
    agent_id: str,
    stage_key: str,
    db: AsyncSession | None = None,
    owner_id: uuid.UUID | str | None = None,
) -> SkillContract | None:
    """按 (agent_id, stage_key) 解析该 Agent 应使用的 skill.

    多命中时按 version 取最高并记 warning（同名唯一性由 DB 约束保证，
    「不同名但同 agent」属配置错误，**必须暴露**而不是静默取第一个）。
    """
    all_skills = await list_skills(db, owner_id)
    matched = [c for c in all_skills if c.agent_id == agent_id and c.stage_key == stage_key]
    if not matched:
        return None
    if len(matched) > 1:
        logger.warning(
            "同一 (agent_id=%s, stage_key=%s) 命中 %d 个 skill：%s —— 按 version 取最高",
            agent_id,
            stage_key,
            len(matched),
            [c.name for c in matched],
        )
        matched.sort(key=lambda c: c.version, reverse=True)
    return matched[0]


def invalidate() -> None:
    """清空用户层缓存（api 层写操作 commit 后调用）."""
    _user_cache.clear()


def invalidate_user(owner_id: uuid.UUID | str) -> None:
    """粒度更细的失效入口（当前用户层共享，语义等同 invalidate）.

    保留该签名是为未来「按 owner 隔离」时无需改调用方。
    """
    _user_cache.clear()
