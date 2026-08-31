"""章节分工服务 — 分配 upsert（含子节展开）、树形分工列表、最小粒度编辑权限判定."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ForbiddenError, ValidationError
from app.core.sorting import natural_sort_key, numbered_sections
from app.models.project import Project, ProjectMember
from app.models.proposal import (
    ChapterAnnotation,
    ChapterAssignment,
    ProposalSection,
    ProposalSkeleton,
)
from app.models.user import User

ASSIGNMENT_STATUSES = ("pending", "in_progress", "submitted", "approved", "rejected")


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


async def _load_outline(db: AsyncSession, project_id: uuid.UUID) -> list[dict]:
    """读取已确认大纲（proposal_skeletons.tree）；无骨架返回 []."""
    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton or not skeleton.tree:
        return []
    tree = skeleton.tree
    return tree if isinstance(tree, list) else []


async def assign_chapters(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> list[ChapterAssignment]:
    """批量分配章节/子节负责人（幂等 upsert）.

    items: [{chapter_no, title, assignee_id}]；chapter_no 支持子节编号（如 1.1）。
    章级分配且大纲含嵌套子节时 = 自动展开为其全部子节批量分配（不再保留
    章级分工记录，原章级分工被替换删除）；已分配条目更新负责人并重置为 pending。
    assignee 必须是项目成员，否则 4004。
    """
    outline = await _load_outline(db, project_id)

    # 章级条目展开为子节（大纲嵌套树驱动；string[] 大纲保持章级）
    expanded: list[dict[str, Any]] = []
    for item in items:
        chapter_no = str(item.get("chapter_no") or "").strip()
        chapter = next((c for c in outline if str(c.get("chapter_no", "")) == chapter_no), None)
        subs = numbered_sections((chapter or {}).get("sections", []) or [], chapter_no)
        if chapter is not None and subs:
            for no, title in subs:
                expanded.append({**item, "chapter_no": no, "title": title})
            # 章级分工被子节分工替换：清理旧章级记录（含其流转状态）
            result = await db.execute(
                select(ChapterAssignment).where(
                    ChapterAssignment.project_id == project_id,
                    ChapterAssignment.chapter_no == chapter_no,
                )
            )
            stale = result.scalar_one_or_none()
            if stale is not None:
                await db.delete(stale)
        else:
            expanded.append(item)

    assignments: list[ChapterAssignment] = []
    for item in expanded:
        chapter_no = str(item.get("chapter_no") or "").strip()
        title = str(item.get("title") or "").strip()
        assignee_raw = item.get("assignee_id")
        if not chapter_no or not title or not assignee_raw:
            raise BizError(code=4000, message="分工条目缺少 chapter_no/title/assignee_id")
        try:
            assignee_id = uuid.UUID(str(assignee_raw))
        except ValueError:
            raise BizError(code=4000, message="assignee_id 格式错误") from None

        if not await _is_project_member(db, project_id, assignee_id):
            raise BizError(code=4004, message=f"章节 {chapter_no} 的负责人不是项目成员")

        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == chapter_no,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment:
            # 重新分配：更新负责人并重置流转状态
            assignment.title = title
            assignment.assignee_id = assignee_id
            assignment.assigned_by = owner_id
            assignment.status = "pending"
            assignment.review_comment = None
            assignment.assigned_at = datetime.now(UTC)
            assignment.accepted_at = None
            assignment.submitted_at = None
            assignment.reviewed_at = None
        else:
            assignment = ChapterAssignment(
                project_id=project_id,
                chapter_no=chapter_no,
                title=title,
                assignee_id=assignee_id,
                assigned_by=owner_id,
                status="pending",
            )
            db.add(assignment)
        assignments.append(assignment)
    await db.flush()
    return assignments


def _assignment_dict(
    assignment: ChapterAssignment, user: User, section_status: str | None
) -> dict[str, Any]:
    """分工记录 → API 字典（负责人 display_name + 章节内容状态）."""

    def _iso(ts: datetime | None) -> str | None:
        return ts.isoformat() if ts else None

    name = user.display_name or user.email
    return {
        "id": str(assignment.id),
        "chapter_no": assignment.chapter_no,
        "title": assignment.title,
        "assignee_id": str(assignment.assignee_id),
        "assignee_name": name,
        # 提交人即负责人（编制提交由 assignee 发起，审阅页标注用）
        "submitted_by_name": name,
        "assigned_by": str(assignment.assigned_by),
        "status": assignment.status,
        "section_status": section_status,
        "review_comment": assignment.review_comment,
        "assigned_at": _iso(assignment.assigned_at),
        "accepted_at": _iso(assignment.accepted_at),
        "submitted_at": _iso(assignment.submitted_at),
        "reviewed_at": _iso(assignment.reviewed_at),
        "children": [],
        "total": 0,
        "approved_count": 0,
    }


def _aggregate_status(children: list[dict[str, Any]]) -> str | None:
    """章级聚合状态（无自身分工时）：全 approved > submitted > rejected > in_progress > pending."""
    statuses = [c["status"] for c in children]
    if not statuses:
        return None
    if all(s == "approved" for s in statuses):
        return "approved"
    for s in ("submitted", "rejected", "in_progress"):
        if any(x == s for x in statuses):
            return s
    return "pending"


async def list_assignments(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """分工列表（树形）：章行附 children（子节分工）与聚合字段 approved_count/total.

    章级分配已展开为子节时，章行作为聚合行返回（id/assignee 为 None，status 取聚合）；
    无任何分工的章不出现在列表（分配入口由前端大纲驱动）。
    """
    result = await db.execute(
        select(ChapterAssignment, User, ProposalSection.status)
        .join(User, User.id == ChapterAssignment.assignee_id)
        .outerjoin(
            ProposalSection,
            (ProposalSection.project_id == ChapterAssignment.project_id)
            & (ProposalSection.section_id == ChapterAssignment.chapter_no),
        )
        .where(ChapterAssignment.project_id == project_id)
    )
    rows: dict[str, dict[str, Any]] = {}
    for assignment, user, section_status in result.all():
        rows[assignment.chapter_no] = _assignment_dict(assignment, user, section_status)

    outline = await _load_outline(db, project_id)
    items: list[dict[str, Any]] = []
    used: set[str] = set()
    for chapter in outline:
        no = str(chapter.get("chapter_no", ""))
        if not no:
            continue
        children = sorted(
            (row for rn, row in rows.items() if rn.startswith(f"{no}.")),
            key=lambda r: natural_sort_key(r["chapter_no"]),
        )
        own = rows.get(no)
        if own is None and not children:
            continue
        if own is None:
            # 章级展开为子节后章行做聚合：若全部子节为同一负责人则回填
            # assignee_id/assignee_name，前端下拉框推送后保持选中（二次推送体验）
            child_assignees = {c["assignee_id"] for c in children if c.get("assignee_id")}
            uniform_assignee = child_assignees.pop() if len(child_assignees) == 1 else None
            uniform_name = None
            if uniform_assignee:
                uniform_name = next(
                    (
                        c["assignee_name"]
                        for c in children
                        if c.get("assignee_id") == uniform_assignee
                    ),
                    None,
                )
            own = {
                "id": None,
                "chapter_no": no,
                "title": str(chapter.get("title", "")),
                "assignee_id": uniform_assignee,
                "assignee_name": uniform_name,
                "submitted_by_name": None,
                "assigned_by": None,
                "status": _aggregate_status(children),
                "section_status": None,
                "review_comment": None,
                "assigned_at": None,
                "accepted_at": None,
                "submitted_at": None,
                "reviewed_at": None,
            }
        own["children"] = children
        own["total"] = len(children)
        own["approved_count"] = sum(1 for c in children if c["status"] == "approved")
        items.append(own)
        used.add(no)
        used.update(c["chapter_no"] for c in children)

    # 大纲外的孤儿分工（大纲二次编辑删除章节等脏数据兼容）
    for rn in sorted(rows, key=natural_sort_key):
        if rn not in used:
            items.append(rows[rn])
    return items


async def get_assignment(
    db: AsyncSession, project_id: uuid.UUID, assignment_id: uuid.UUID
) -> ChapterAssignment | None:
    """按 id 读取项目内的分工记录."""
    result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.id == assignment_id,
            ChapterAssignment.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def _owner_fallback(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """owner 兜底判定（调用方未传 is_owner 时查项目 owner）."""
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    return bool(project and project.owner_id == user_id)


async def check_chapter_editable(
    db: AsyncSession,
    project_id: uuid.UUID,
    chapter_no: str,
    user_id: uuid.UUID,
    is_owner: bool = False,
) -> bool:
    """最小粒度编辑权限（可视不可改）.

    - 本编号有分工 → 仅该分工 assignee/owner 可编辑；
    - 子节无分工但父章有分工 → 父章 assignee/owner 可编辑（章级分工覆盖子节）；
    - 章下存在子节分工 → 任一子节 assignee/owner 可编辑整章；
    - 无任何分工 → 仅 owner 可编辑（行为收紧，废弃「未分配成员可编辑」兼容）。
    """
    if is_owner:
        return True

    result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.project_id == project_id,
            ChapterAssignment.chapter_no == chapter_no,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is not None:
        if assignment.assignee_id == user_id:
            return True
        return await _owner_fallback(db, project_id, user_id)

    # 子节编号：父章分工覆盖（1.1 无分工 → 查 1）
    if "." in chapter_no:
        parent_no = chapter_no.rsplit(".", 1)[0]
        parent_result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == parent_no,
            )
        )
        parent = parent_result.scalar_one_or_none()
        if parent is not None:
            if parent.assignee_id == user_id:
                return True
            return await _owner_fallback(db, project_id, user_id)

    # 章下子节分工：任一子节 assignee 可编辑整章
    children_result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.project_id == project_id,
            ChapterAssignment.chapter_no.startswith(f"{chapter_no}."),
        )
    )
    children = children_result.scalars().all()
    if children:
        if any(c.assignee_id == user_id for c in children):
            return True
        return await _owner_fallback(db, project_id, user_id)

    # 无任何分工 → 仅 owner（收紧）
    return await _owner_fallback(db, project_id, user_id)


# ───────────────────────── 项目载入与状态机流转（批次 1c 自 api 下沉） ─────────────────────────


async def get_project(db: AsyncSession, project_id: uuid.UUID) -> Project | None:
    """按 id 载入项目（不含归属校验，供提交推送/批注权限/自动快照钩子使用）."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def accept_assignment(db: AsyncSession, assignment: ChapterAssignment) -> None:
    """领取任务：pending/rejected → in_progress（仅 flush 不 commit）."""
    if assignment.status not in ("pending", "rejected"):
        raise ValidationError(f"当前状态 {assignment.status} 不可领取")
    assignment.status = "in_progress"
    assignment.accepted_at = datetime.now(UTC)
    await db.flush()


async def submit_assignment(db: AsyncSession, assignment: ChapterAssignment) -> None:
    """提交待审：in_progress/rejected → submitted（仅 flush 不 commit）."""
    if assignment.status not in ("in_progress", "rejected"):
        raise ValidationError(f"当前状态 {assignment.status} 不可提交")
    assignment.status = "submitted"
    assignment.submitted_at = datetime.now(UTC)
    await db.flush()


async def review_assignment(
    db: AsyncSession, assignment: ChapterAssignment, action: str, comment: str
) -> None:
    """负责人审核：submitted → approved/rejected（rejected 回退可重编；仅 flush 不 commit）."""
    if assignment.status != "submitted":
        raise ValidationError(f"当前状态 {assignment.status} 不可审核（仅待审章节可审核）")
    assignment.status = action
    assignment.review_comment = comment or None
    assignment.reviewed_at = datetime.now(UTC)
    await db.flush()


# ───────────────────────── 章节批注（分工维度，批次 1c 自 api 下沉） ─────────────────────────


async def list_annotations(
    db: AsyncSession, project_id: uuid.UUID, chapter_no: str
) -> list[dict[str, Any]]:
    """章节批注列表（JOIN 作者 display_name，按时间正序）."""
    result = await db.execute(
        select(ChapterAnnotation, User.display_name)
        .join(User, User.id == ChapterAnnotation.created_by)
        .where(
            ChapterAnnotation.project_id == project_id,
            ChapterAnnotation.chapter_no == chapter_no,
        )
        .order_by(ChapterAnnotation.created_at.asc())
    )
    return [
        {
            "id": str(ann.id),
            "chapter_no": ann.chapter_no,
            "content": ann.content,
            "created_by": str(ann.created_by),
            "created_by_name": name or "",
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        }
        for ann, name in result.all()
    ]


async def create_annotation(
    db: AsyncSession,
    project_id: uuid.UUID,
    assignment: ChapterAssignment,
    content: str,
    user_id: uuid.UUID,
) -> ChapterAnnotation:
    """新增章节批注（assignee 或项目 owner 可写；仅 flush 不 commit）.

    与审核打回意见字段（review_comment）并存。
    """
    project = await get_project(db, project_id)
    is_owner = project is not None and project.owner_id == user_id
    if assignment.assignee_id != user_id and not is_owner:
        raise ForbiddenError("仅章节负责人或项目负责人可批注")

    ann = ChapterAnnotation(
        project_id=project_id,
        chapter_no=assignment.chapter_no,
        content=content.strip(),
        created_by=user_id,
    )
    db.add(ann)
    await db.flush()
    await db.refresh(ann)
    return ann


# ───────────────────────── 章节内容读写（content Markdown + content_html 富文本）


async def get_assignment_by_chapter(
    db: AsyncSession, project_id: uuid.UUID, chapter_no: str
) -> ChapterAssignment | None:
    """按章节号读取分工记录（内容读写端点定位载体；不存在返 None）."""
    result = await db.execute(
        select(ChapterAssignment).where(
            ChapterAssignment.project_id == project_id,
            ChapterAssignment.chapter_no == chapter_no,
        )
    )
    return result.scalar_one_or_none()


async def update_chapter_content(
    db: AsyncSession, assignment: ChapterAssignment, content: str, content_html: str | None
) -> None:
    """保存章节内容（Markdown + 富文本 HTML 双字段；仅 flush 不 commit）."""
    assignment.content = content
    assignment.content_html = content_html
    await db.flush()
