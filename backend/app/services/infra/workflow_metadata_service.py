"""工作流元数据持久化服务 — ProposalWorkflow CRUD.

Phase 4 从 agents/nodes/_shared.py 迁入，消除 agents 层直接操作 ORM.
"""

import uuid

from sqlalchemy import select

from app.models.proposal import ProposalWorkflow


async def update_workflow(
    db,
    project_id: str,
    *,
    phase: str | None = None,
    progress: float | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """创建或更新项目工作流元数据."""
    result = await db.execute(
        select(ProposalWorkflow).where(ProposalWorkflow.project_id == uuid.UUID(project_id))
    )
    wf = result.scalar_one_or_none()
    if not wf:
        wf = ProposalWorkflow(project_id=uuid.UUID(project_id), thread_id=str(project_id))
        db.add(wf)
    if phase is not None:
        wf.phase = phase
    if progress is not None:
        wf.progress = progress
    if status is not None:
        wf.status = status
    if error is not None:
        wf.error = error
    await db.flush()
