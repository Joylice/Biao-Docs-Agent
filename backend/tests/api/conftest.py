"""tests/api 共享 fixture — RBAC 种子桩（隔离模块级缓存与 mock 会话）."""

import pytest

from app.core import rbac

# 与迁移 0011 种子一致：API 测试以固定映射判定权限，避免 mock 会话为
# RolePermission 查询额外消耗 execute 预设，同时消除对模块级缓存的顺序依赖
SEED_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "member": frozenset({"kb:read", "kb:upload", "settings:read"}),
    "kb_admin": frozenset({"kb:read", "kb:upload", "settings:read", "kb:manage"}),
    "admin": frozenset({"system:manage", "kb:manage", "kb:read", "kb:upload", "settings:read"}),
}


@pytest.fixture(autouse=True)
def _rbac_seed(monkeypatch: pytest.MonkeyPatch):
    """API 测试统一使用种子角色映射；用例前后清空模块级缓存防污染.

    load_role_permissions 的真实加载/缓存行为由 tests/unit/test_rbac.py 覆盖，
    此处仅按迁移种子固定「角色 → 权限点」判定结果。
    """
    rbac.invalidate_rbac_cache()

    async def _seed_load(_db) -> dict[str, frozenset[str]]:
        return SEED_ROLE_PERMISSIONS

    monkeypatch.setattr("app.core.rbac.load_role_permissions", _seed_load)
    yield
    rbac.invalidate_rbac_cache()
