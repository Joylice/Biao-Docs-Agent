"""RBAC 模型 — roles / permissions / role_permissions（迁移 0011_rbac）.

完整 RBAC 落地（2026-08-17）：功能权限（角色 → 权限点）落库；users.role 字符串列
保留不动（兼容既有数据与代码），require_permission 以 users.role → role_permissions 判定。
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(Base):
    """角色表（users.role 关联的角色定义）."""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Permission(Base):
    """权限点表."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)


class RolePermission(Base):
    """角色-权限映射表."""

    __tablename__ = "role_permissions"

    role_code: Mapped[str] = mapped_column(String(20), ForeignKey("roles.code"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("permissions.code"), primary_key=True
    )
