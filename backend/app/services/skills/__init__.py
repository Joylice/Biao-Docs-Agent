"""Skill 体系 — 契约/加载/注册表/服务.

模块职责（依赖方向：services.skills → infra.*，单向）：
- contract: SKILL.md 解析 + 契约校验 + 渲染
- loader:   内置层扫描（backend/skills/*/SKILL.md，目录 mtime 缓存）
- registry: listSkills 双源合并（内置文件系统 + 用户 DB）
- service:  用户层 CRUD（乐观锁 + TTL 缓存 + 降级包裹）
- zip_io:   zip 安全导入导出（三重防护）
"""

from app.services.skills.contract import (
    SKILL_BODY_MAX_CHARS,
    SKILL_NAME_PATTERN,
    SkillContract,
    SkillContractError,
    parse_skill_md,
    render_skill_prompt,
    validate_contract,
    wrap_user_skill_content,
)

__all__ = [
    "SKILL_BODY_MAX_CHARS",
    "SKILL_NAME_PATTERN",
    "SkillContract",
    "SkillContractError",
    "parse_skill_md",
    "render_skill_prompt",
    "validate_contract",
    "wrap_user_skill_content",
]
