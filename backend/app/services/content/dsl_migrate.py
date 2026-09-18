"""DSL 版本迁移注册表 — 参照 OpenMAIC migration ladder.

当 DSL Schema 演化时（新增 block 类型、字段重命名等），
通过 migration ladder 将旧版本文档升级到当前版本。
"""

from __future__ import annotations

from app.services.content.dsl_types import DSL_VERSION, ProposalContent

# 迁移函数链：[(from_version, to_version, migrate_fn), ...]
# 新增迁移时追加到链尾，保持有序
_MIGRATIONS: list[tuple[int, int]] = []


def needs_migration(content: ProposalContent) -> bool:
    """检查文档是否需要迁移."""
    return content.version < DSL_VERSION


def migrate(content: ProposalContent) -> ProposalContent:
    """将旧版本 DSL 文档迁移到当前版本.

    遍历 migration ladder，逐步升级到 DSL_VERSION。
    当前只有 version=1，无实际迁移函数（预留）。
    """
    if content.version >= DSL_VERSION:
        return content

    # 预留：未来版本迁移逻辑
    # for from_v, to_v in _MIGRATIONS:
    #     if content.version == from_v:
    #         content = _apply_migration(content, from_v, to_v)

    content.version = DSL_VERSION
    return content
