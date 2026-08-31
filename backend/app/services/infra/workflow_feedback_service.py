"""审阅意见回派服务 — 成员收集与意见分发.

从 workflow_runtime.py 拆分（Phase 3 上帝模块治理）.
"""

import uuid
from datetime import UTC, datetime

from app.core.sorting import numbered_sections


async def list_project_member_ids(db, project_id: uuid.UUID) -> list[uuid.UUID]:
    """项目成员 user_id 列表（confirm-outline 用户级推送目标收集）."""
    from sqlalchemy import select

    from app.models.project import ProjectMember

    result = await db.execute(
        select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    )
    return list(result.scalars().all())


async def redispatch_feedback(
    db, project_id: uuid.UUID, feedback: dict[str, str]
) -> tuple[dict[str, str], list[dict]]:
    """审阅意见回派章节/子节负责人（阶段 5）.

    feedback 键支持章级/子节编号或标题匹配（子节编号/标题来自大纲嵌套树）：
    - 命中分工 → assignment 置 rejected + 意见落库
      （assignee 在分工页「我的任务」看到打回可重编）；
    - 子节无分工时降级匹配父章分工；
    - 无分工章节 → 保留原 rewrite 链路。
    返回 (未被回派的剩余 feedback, 待推送的 task_reviewed 事件列表)，
    事件推送由 api 层执行；仅 flush 不 commit（BUG-1：api 层在 resume 前显式提交）。
    """
    if not feedback:
        return {}, []
    from sqlalchemy import select

    from app.models.proposal import ChapterAssignment
    from app.services.infra.workflow_runtime import get_state

    snapshot = await get_state(project_id)
    outline = (snapshot.values or {}).get("outline", []) or []
    nos: set[str] = set()
    title_to_no: dict[str, str] = {}
    for c in outline:
        no = str(c.get("chapter_no", ""))
        nos.add(no)
        title_to_no[str(c.get("title", ""))] = no
        for sub_no, sub_title in numbered_sections(c.get("sections", []) or [], no):
            nos.add(sub_no)
            title_to_no.setdefault(sub_title, sub_no)
    remaining: dict[str, str] = {}
    events: list[dict] = []
    for key, comment in feedback.items():
        chapter_no = key if key in nos else title_to_no.get(key, "")
        if not chapter_no:
            remaining[key] = comment
            continue
        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.project_id == project_id,
                ChapterAssignment.chapter_no == chapter_no,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment is None and "." in chapter_no:
            parent_no = chapter_no.rsplit(".", 1)[0]
            result = await db.execute(
                select(ChapterAssignment).where(
                    ChapterAssignment.project_id == project_id,
                    ChapterAssignment.chapter_no == parent_no,
                )
            )
            assignment = result.scalar_one_or_none()
        if assignment is None:
            remaining[key] = comment
            continue
        assignment.status = "rejected"
        assignment.review_comment = comment
        assignment.reviewed_at = datetime.now(UTC)
        events.append(
            {
                "type": "task_reviewed",
                "chapter_no": chapter_no,
                "assignee_id": str(assignment.assignee_id),
                "action": "rejected",
            }
        )
    await db.flush()
    return remaining, events
