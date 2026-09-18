"""RBAC 权限体系：roles / permissions / role_permissions 三表 + 种子数据.

完整 RBAC 落地（2026-08-17）：功能权限（角色 → 权限点）落库；users.role 字符串列
保留兼容既有数据与代码，require_permission 以 users.role → role_permissions 判定。
双维模型：功能权限（RBAC）+ 数据范围（项目成员表 / owner 属性，project:member_manage
为 owner 数据属性，仅作权限点目录登记，不映射角色）。

Revision ID: 0011_rbac
Revises: 0010_skeleton_outline_draft
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_rbac"
down_revision: str | None = "0010_skeleton_outline_draft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_SEEDS = [
    {"code": "member", "name": "普通用户", "description": "项目协作与资料库基础使用"},
    {"code": "kb_admin", "name": "资料库管理员", "description": "全局资料库编辑/删除"},
    {"code": "admin", "name": "系统管理员", "description": "用户/审计/模型设置等系统管理"},
]

PERMISSION_SEEDS = [
    {"code": "system:manage", "name": "系统管理（用户/审计/模型设置）", "category": "system"},
    {"code": "kb:manage", "name": "资料库管理（编辑/删除）", "category": "kb"},
    {"code": "kb:read", "name": "资料库读取（列表/检索）", "category": "kb"},
    {"code": "kb:upload", "name": "资料库上传", "category": "kb"},
    {"code": "settings:read", "name": "LLM 配置读取", "category": "settings"},
    # project:member_manage 为 owner 数据属性（不走角色表），仅作权限点目录登记
    {
        "code": "project:member_manage",
        "name": "项目成员管理（owner 数据属性）",
        "category": "project",
    },
]

ROLE_PERMISSION_SEEDS = [
    ("member", "kb:read"),
    ("member", "kb:upload"),
    ("member", "settings:read"),
    ("kb_admin", "kb:read"),
    ("kb_admin", "kb:upload"),
    ("kb_admin", "settings:read"),
    ("kb_admin", "kb:manage"),
    ("admin", "system:manage"),
    ("admin", "kb:manage"),
    ("admin", "kb:read"),
    ("admin", "kb:upload"),
    ("admin", "settings:read"),
]


def upgrade() -> None:
    """三表 + 种子（幂等：permissions 非空时跳过，支持重复执行）."""
    op.create_table(
        "roles",
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_code", sa.String(20), sa.ForeignKey("roles.code"), primary_key=True),
        sa.Column(
            "permission_code", sa.String(50), sa.ForeignKey("permissions.code"), primary_key=True
        ),
    )

    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT count(*) FROM permissions")).scalar()
    if existing:
        return

    roles_tbl = sa.table(
        "roles",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
    )
    perms_tbl = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
    )
    rp_tbl = sa.table(
        "role_permissions",
        sa.column("role_code", sa.String),
        sa.column("permission_code", sa.String),
    )
    op.bulk_insert(roles_tbl, ROLE_SEEDS)
    op.bulk_insert(perms_tbl, PERMISSION_SEEDS)
    op.bulk_insert(
        rp_tbl, [{"role_code": r, "permission_code": p} for r, p in ROLE_PERMISSION_SEEDS]
    )


def downgrade() -> None:
    """回滚：删除三表（角色/权限数据随之丢弃）."""
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
