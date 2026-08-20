"""知识库服务 — 多知识库（个人/项目/公司）可见性矩阵与检索范围解析."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ForbiddenError, NotFoundError
from app.models.document import Document
from app.models.knowledge_base import (
    SCOPE_COMPANY,
    SCOPE_PERSONAL,
    SCOPE_PROJECT,
    VALID_SCOPES,
    KnowledgeBase,
)
from app.models.project import Project, ProjectMember

COMPANY_PUBLIC_BASE_NAME = "公司公共库"


async def _is_project_member(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """成员归属判定：owner 或 project_members 在表."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project and project.owner_id == user_id:
        return True
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return member_result.scalar_one_or_none() is not None


async def is_project_member(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """成员归属判定（公开入口）."""
    return await _is_project_member(db, project_id, user_id)


async def _is_kb_admin(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """资料库管理员判定（kb:manage 权限点，白名单兼容在 has_permission 内）."""
    from app.core.rbac import has_permission
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False
    return await has_permission(db, user, "kb:manage")


async def list_visible_bases(
    db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """可见知识库列表（含素材数）：公司全员 / 个人仅本人 / 项目限成员.

    无项目上下文（全局资料页，阶段 3）：列出用户所属全部项目的库；
    带项目上下文：仅列该项目的库。项目库项附 project_name 供前端标注归属。
    """
    result = await db.execute(select(KnowledgeBase))
    bases = list(result.scalars().all())

    counts_result = await db.execute(
        select(Document.kb_id, func.count(Document.id))
        .where(Document.doc_type == "kb_material", Document.kb_id.is_not(None))
        .group_by(Document.kb_id)
    )
    counts = {row[0]: row[1] for row in counts_result.all()}

    # 项目库归属项目名（批量一次）
    project_pids = {b.project_id for b in bases if b.scope == SCOPE_PROJECT and b.project_id}
    project_names: dict[uuid.UUID, str] = {}
    if project_pids:
        p_result = await db.execute(select(Project).where(Project.id.in_(project_pids)))
        project_names = {p.id: p.name for p in p_result.scalars().all()}

    items: list[dict[str, Any]] = []
    order = {SCOPE_COMPANY: 0, SCOPE_PROJECT: 1, SCOPE_PERSONAL: 2}
    for base in bases:
        if base.scope == SCOPE_COMPANY:
            visible = True
        elif base.scope == SCOPE_PERSONAL:
            visible = base.owner_id == user_id
        elif base.scope == SCOPE_PROJECT:
            # 带项目上下文：仅该项目的库且需成员身份；
            # 无上下文（全局资料页）：用户所属任一项目的库均可见（阶段 3）
            if base.project_id is None:
                visible = False
            elif project_id is not None:
                visible = base.project_id == project_id and await _is_project_member(
                    db, base.project_id, user_id
                )
            else:
                visible = await _is_project_member(db, base.project_id, user_id)
        else:
            visible = False
        if not visible:
            continue
        items.append(
            {
                "id": str(base.id),
                "name": base.name,
                "description": base.description,
                "scope": base.scope,
                "project_id": str(base.project_id) if base.project_id else None,
                "project_name": project_names.get(base.project_id) if base.project_id else None,
                "owner_id": str(base.owner_id) if base.owner_id else None,
                "material_count": counts.get(base.id, 0),
                "created_at": base.created_at.isoformat() if base.created_at else None,
            }
        )
    items.sort(key=lambda x: (order.get(x["scope"], 9), x["name"]))
    return items


async def create_base(
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    name: str,
    description: str | None = None,
    project_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    """创建知识库（权限：personal 任意登录用户 / project 仅 owner / company 仅管理员）."""
    if scope not in VALID_SCOPES:
        raise BizError(code=4000, message=f"scope 非法：{scope}")
    name = (name or "").strip()
    if not name:
        raise BizError(code=4000, message="知识库名称不能为空")

    if scope == SCOPE_PROJECT:
        if project_id is None:
            raise BizError(code=4000, message="项目级知识库必须指定 project_id")
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise NotFoundError("项目")
        if project.owner_id != user_id:
            raise ForbiddenError("仅项目创建者可创建项目级知识库")
    elif scope == SCOPE_COMPANY:
        if not await _is_kb_admin(db, user_id):
            raise ForbiddenError("仅资料库管理员可创建公司级知识库")
        project_id = None
    else:  # personal
        project_id = None

    # 同域重名校验（personal 按 owner、project 按项目、company 全局）
    dup_query = select(KnowledgeBase).where(
        KnowledgeBase.scope == scope, KnowledgeBase.name == name
    )
    if scope == SCOPE_PERSONAL:
        dup_query = dup_query.where(KnowledgeBase.owner_id == user_id)
    elif scope == SCOPE_PROJECT:
        dup_query = dup_query.where(KnowledgeBase.project_id == project_id)
    dup = (await db.execute(dup_query)).scalar_one_or_none()
    if dup:
        raise BizError(code=4000, message="同范围内已存在同名知识库")

    base = KnowledgeBase(
        project_id=project_id,
        owner_id=user_id if scope != SCOPE_COMPANY else None,
        scope=scope,
        name=name,
        description=(description or "").strip() or None,
    )
    db.add(base)
    await db.flush()
    await db.refresh(base)
    return base


async def check_base_writable(db: AsyncSession, base: KnowledgeBase, user_id: uuid.UUID) -> None:
    """库写权限校验（编辑/删除/上传素材入口复用），无权抛 ForbiddenError."""
    if base.scope == SCOPE_PERSONAL:
        if base.owner_id != user_id:
            raise ForbiddenError("仅知识库创建者可操作该个人库")
    elif base.scope == SCOPE_PROJECT:
        if base.project_id is None:
            raise ForbiddenError("项目库缺少项目归属")
        result = await db.execute(select(Project).where(Project.id == base.project_id))
        project = result.scalar_one_or_none()
        if not project or project.owner_id != user_id:
            raise ForbiddenError("仅项目创建者可操作该项目库")
    else:  # company
        if not await _is_kb_admin(db, user_id):
            raise ForbiddenError("仅资料库管理员可操作公司级知识库")


async def resolve_doc_ids(db: AsyncSession, base_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """知识库 → 库内素材 doc_id 列表（仅 kb_material）."""
    if not base_ids:
        return []
    result = await db.execute(
        select(Document.id).where(Document.doc_type == "kb_material", Document.kb_id.in_(base_ids))
    )
    return [row[0] for row in result.all()]


async def resolve_mount_doc_ids(
    db: AsyncSession,
    mounted_kb_ids: list[str] | None,
    mounted_doc_ids: list[str] | None,
) -> list[uuid.UUID] | None:
    """合并挂载配置为检索 doc_ids（库级与文档级并集；两者均 None = 项目全量）."""
    if mounted_kb_ids is None and mounted_doc_ids is None:
        return None
    doc_id_set: set[uuid.UUID] = set()
    if mounted_kb_ids is not None:
        kb_uuids = [uuid.UUID(str(k)) for k in mounted_kb_ids]
        doc_id_set.update(await resolve_doc_ids(db, kb_uuids))
    if mounted_doc_ids is not None:
        doc_id_set.update(uuid.UUID(str(d)) for d in mounted_doc_ids)
    return sorted(doc_id_set, key=str)


def material_visibility_clause(user_id: uuid.UUID, member_alias):
    """素材可见性 SQL 条件（documents LEFT JOIN knowledge_bases + 项目成员判定）.

    返回 or_ 条件：kb_id IS NULL（存量未归档）/ 公司库 / 本人个人库 /
    用户所属项目的项目库（member_alias 为 ProjectMember 外连接的 user_id 列）.
    """
    return or_(
        Document.kb_id.is_(None),
        KnowledgeBase.scope == SCOPE_COMPANY,
        (KnowledgeBase.scope == SCOPE_PERSONAL) & (KnowledgeBase.owner_id == user_id),
        (KnowledgeBase.scope == SCOPE_PROJECT) & member_alias.is_not(None),
    )
