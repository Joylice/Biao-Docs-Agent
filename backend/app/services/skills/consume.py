"""Skill 消费入口 — Agent Runtime 按需取用行为准则（S3）.

本模块是**唯一的「skill → 提示词」桥**。所有 stage 的提示词加载最终都经过这里：

    stage 提示词入口（prompt_loader.load_*_prompt / parsing.prompts）
        → resolve_skill_prompt(skill_name, context)   ← 本模块
            → registry 查注册表（用户层覆盖内置层）
            → contract.render_skill_prompt() 渲染数据注入
            → 用户层内容做降级包裹（wrap_user_skill_content）

为什么要「统一入口」而不是各处直接调 registry：
1. **降级不阻断**：registry 或契约出错时必须回退到旧 YAML，绝不能让「准则是新的」
   变成「方案编不出来」。降级路径写在一处，不需要 9 个调用点各写一遍。
2. **可观测**：每次解析都记 `skill=<name> source=<builtin|user>`，
   归因「模型行为变了是不是因为某条准则被改」时有据可查（S5 会把这行升级为落库）。
3. **无 DB 也要能跑**：单测/E2E/离线批处理没有 DB session，
   此时只走内置层 —— 保证「契约体系引入」不成为新增强制依赖。

与旧 PromptComposer 的关系：**并存**。旧 `prompt_loader.load_*_prompt()` 保留为
降级路径（S6 才删旧 YAML + 删回退分支）。本模块负责「新路径优先」。

`user_invocable=False` 的 skill **不可被用户层覆盖**：即使 DB 里有同名行也拒绝采用，
回退内置 —— 这是契约里「本 skill 的行为由系统固化、用户不得改写」的表达方式。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from app.services.skills import registry
from app.services.skills.contract import SkillContract, render_skill_prompt, wrap_user_skill_content

logger = logging.getLogger(__name__)


class SkillNotFound(Exception):
    """注册表中不存在该 skill（调用方应回退旧 YAML —— 降级不阻断）."""


def _render_and_wrap(contract: SkillContract, context: dict[str, Any]) -> tuple[str, str]:
    """渲染契约 → (system_prompt, user_prompt)，并按来源层决定是否降级包裹."""
    system_prompt, user_prompt = render_skill_prompt(contract, context)
    # 用「已渲染 body」替换原 body，其余字段不变（dataclasses.replace 保证不漏字段）
    wrapped = replace(contract, body=system_prompt)
    return wrap_user_skill_content(wrapped), user_prompt


def _log_resolution(contract: SkillContract, system: str, user: str) -> None:
    logger.info(
        "skill 已解析: skill=%s source=%s version=%s agent=%s system_chars=%d user_chars=%d",
        contract.name,
        "builtin" if contract.builtin else "user",
        contract.version,
        contract.agent_id,
        len(system),
        len(user),
    )


async def resolve_contract(
    skill_name: str,
    db: Any = None,
    *,
    owner_id: Any = None,
) -> SkillContract:
    """按名解析 skill 契约（用户层覆盖内置层）.

    Raises:
        SkillNotFound: 注册表两层都没有该 skill。
    """
    contract = await registry.find_skill(skill_name, db, owner_id)
    if contract is None:
        raise SkillNotFound(f"skill '{skill_name}' 不在注册表（内置层 + 用户层均未命中）")
    return contract


async def resolve_skill_prompt(
    skill_name: str,
    context: dict[str, Any],
    db: Any = None,
    *,
    owner_id: Any = None,
) -> tuple[str, str, SkillContract]:
    """解析 skill 并渲染成 (system_prompt, user_prompt, contract).

    Args:
        skill_name: 契约名（如 "outline" / "parse_score"）。
        context: 数据注入上下文（与旧 DSL 的 compose context 同构）。
        db: DB session；None 时只走内置层（单测/离线场景）。
        owner_id: 保留参数（产品口径「用户层全员共享」，当前不过滤）。

    Returns:
        (system_prompt, user_prompt, contract) —— 第三项供调用方留痕/归因。

    system_prompt 的用户层内容已做降级包裹（防提示注入）；内置层原样。

    Raises:
        SkillNotFound: 注册表未命中（调用方应捕获并回退旧 YAML）。
    """
    contract = await resolve_contract(skill_name, db, owner_id=owner_id)
    system_prompt, user_prompt = _render_and_wrap(contract, context)
    _log_resolution(contract, system_prompt, user_prompt)
    return system_prompt, user_prompt, contract


async def resolve_agent_skill_prompt(
    agent_id: str,
    stage_key: str,
    context: dict[str, Any],
    db: Any = None,
    *,
    owner_id: Any = None,
) -> tuple[str, str, SkillContract] | None:
    """按 (agent_id, stage_key) 解析（招标解析多 Agent 阶段专用）.

    未命中返回 None（调用方回退旧路径），**不抛异常** ——
    多 Agent 解析有「单 Agent 失败不阻断」的既有降级契约。
    """
    contract = await registry.find_skill_for_agent(agent_id, stage_key, db, owner_id)
    if contract is None:
        return None
    system_prompt, user_prompt = _render_and_wrap(contract, context)
    _log_resolution(contract, system_prompt, user_prompt)
    return system_prompt, user_prompt, contract


__all__ = [
    "SkillNotFound",
    "resolve_agent_skill_prompt",
    "resolve_contract",
    "resolve_skill_prompt",
]
