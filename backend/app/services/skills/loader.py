"""Skill 内置层加载器 — 扫描 backend/skills/*/SKILL.md.

缓存策略：以**目录 mtime** 为失效依据（而非固定 TTL）——
开发期改 SKILL.md 立即生效，无需重启进程；生产期无变更则零 IO 开销。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.skills.contract import (
    SkillContract,
    SkillContractError,
    parse_skill_md,
    validate_contract,
)

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"

# (dir_mtime, skills) — 目录 mtime 变了才重扫
_cache: tuple[float, dict[str, SkillContract]] | None = None


def skills_dir() -> Path:
    """内置 skill 目录（供测试 monkeypatch）."""
    return _SKILLS_DIR


def load_builtin_skills(*, force: bool = False) -> dict[str, SkillContract]:
    """扫描内置 skill 目录，返回 {name: SkillContract}.

    单条 SKILL.md 解析失败**不阻断整体**：记 error 日志后跳过该 skill，
    避免一个坏文件让整条解析链路不可用。
    """
    global _cache

    root = skills_dir()
    if not root.exists():
        logger.warning("内置 skill 目录不存在: %s", root)
        return {}

    try:
        mtime = root.stat().st_mtime
    except OSError:
        mtime = 0.0

    if not force and _cache is not None and _cache[0] == mtime:
        return _cache[1]

    skills: dict[str, SkillContract] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
            contract = parse_skill_md(text, builtin=True, source_path=str(skill_file))
            validate_contract(contract, expected_name=child.name)
        except (SkillContractError, OSError, UnicodeDecodeError) as e:
            logger.error("SKILL.md 加载失败，已跳过: %s（%s）", skill_file, e)
            continue
        if contract.name in skills:
            logger.error("skill 名重复，后者被忽略: %s", contract.name)
            continue
        skills[contract.name] = contract

    _cache = (mtime, skills)
    logger.info("内置 skill 加载完成: %d 个（%s）", len(skills), ", ".join(skills))
    return skills


def invalidate() -> None:
    """清空内置层缓存（api 层写操作或测试用）."""
    global _cache
    _cache = None
