"""大纲二次编辑草稿服务 — 草稿保存/读取/清除.

从 workflow_runtime.py 拆分（Phase 3 上帝模块治理）.
"""

import uuid
from datetime import UTC, datetime


async def save_outline_draft(
    db,
    project_id: uuid.UUID,
    outline: list[dict],
    mounted_doc_ids: list[str] | None = None,
    mounted_kb_ids: list[str] | None = None,
) -> None:
    """保存大纲二次编辑草稿到 proposal_skeletons.draft（行不存在则创建，upsert）.

    draft 结构：{"outline": [...], "mounted_doc_ids": [...], "mounted_kb_ids": [...]}；
    两个挂载列表为字符串列表（None=未设置挂载，保持项目全量检索语义）。
    """
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton:
        skeleton = ProposalSkeleton(project_id=project_id, tree=[])
        db.add(skeleton)
    skeleton.draft = {
        "outline": outline,
        "mounted_doc_ids": mounted_doc_ids,
        "mounted_kb_ids": mounted_kb_ids,
    }
    skeleton.draft_updated_at = datetime.now(UTC)
    await db.flush()


async def get_outline_draft(db, project_id: uuid.UUID) -> dict | None:
    """读取大纲二次编辑草稿；无草稿（或行不存在）返回 None."""
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton or not skeleton.draft:
        return None
    return {
        "outline": skeleton.draft.get("outline", []),
        "mounted_doc_ids": skeleton.draft.get("mounted_doc_ids"),
        "mounted_kb_ids": skeleton.draft.get("mounted_kb_ids"),
        "updated_at": skeleton.draft_updated_at,
    }


async def clear_outline_draft(db, project_id: uuid.UUID) -> None:
    """清除大纲二次编辑草稿（确认成功后调用，幂等）."""
    from sqlalchemy import select

    from app.models.proposal import ProposalSkeleton

    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == project_id)
    )
    skeleton = result.scalar_one_or_none()
    if skeleton:
        skeleton.draft = None
        skeleton.draft_updated_at = None
        await db.flush()
