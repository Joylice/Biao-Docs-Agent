"""方案版本库 API — 列表/手动快照/签名下载/归档公司知识库.

DB 操作统一委托 version_service（批次 1a 分层重构）；
审计留痕/commit/入队保留在 api 层（事务约定 BUG-1）。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_owner_id, get_current_user_id
from app.core.response import success
from app.services import task_service, version_service
from app.services.project_service import _check_project_member
from app.services.storage_service import presigned_url

router = APIRouter()


@router.get("/{project_id}/versions")
async def list_versions(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """版本列表（项目成员可读，version 倒序；created_by NULL = 自动快照）."""
    await _check_project_member(db, project_id, user_id)
    items = await version_service.list_versions(db, project_id)
    return success(data={"items": items})


class SnapshotBody(BaseModel):
    """手动快照请求体 — 备注可选."""

    snapshot_note: str | None = Field(None, max_length=500)


@router.post("/{project_id}/versions")
async def create_version(
    project_id: uuid.UUID,
    body: SnapshotBody | None = None,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动创建版本快照（仅 owner；Word + Markdown 源入 MinIO，version 续号）."""
    project = await version_service.get_project(db, project_id)
    version = await version_service.create_snapshot(
        db,
        project_id,
        project.name,
        user_id=owner_id,
        snapshot_note=body.snapshot_note if body else None,
    )
    await audit.record(
        db,
        owner_id,
        "version.snapshot",
        project_id=project_id,
        target_type="proposal_version",
        target_id=str(version.id),
        detail={"version": version.version},
    )
    await db.commit()
    return success(data={"id": str(version.id), "version": version.version})


@router.get("/{project_id}/versions/{version_id}/download")
async def download_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    type: str = Query(
        "docx", pattern="^(docx|source)$", description="docx=Word/source=Markdown 源"
    ),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """版本下载（项目成员；返回签名 URL，docx 与 Markdown 源二选一）."""
    await _check_project_member(db, project_id, user_id)
    version = await version_service.get_version(db, project_id, version_id)
    storage_key = version.storage_key_docx if type == "docx" else version.storage_key_source
    return success(data={"url": presigned_url(storage_key), "storage_key": storage_key})


class ArchiveBody(BaseModel):
    """归档请求体 — 目标知识库（限公司级）."""

    kb_id: uuid.UUID


@router.post("/{project_id}/versions/{version_id}/rollback")
async def rollback_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """版本回滚（仅 owner）：快照回写 proposal_sections + 图状态，审计 version.rollback."""
    version = await version_service.get_version(db, project_id, version_id)
    chapters_restored = await version_service.rollback_version(db, project_id, version)
    await audit.record(
        db,
        owner_id,
        "version.rollback",
        project_id=project_id,
        target_type="proposal_version",
        target_id=str(version.id),
        detail={"version": version.version, "chapters_restored": chapters_restored},
    )
    await db.commit()
    return success(
        data={
            "id": str(version.id),
            "version": version.version,
            "chapters_restored": chapters_restored,
        }
    )


@router.post("/{project_id}/versions/{version_id}/archive")
async def archive_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ArchiveBody,
    owner_id: uuid.UUID = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """归档版本到公司知识库（仅 owner）：登记全局素材并入队分块向量化."""
    data = await version_service.archive_version(db, project_id, version_id, body.kb_id, owner_id)

    # 审计埋点：方案归档（security.md §4）
    await audit.record(
        db,
        owner_id,
        "proposal.archive",
        project_id=project_id,
        target_type="proposal_version",
        target_id=data["id"],
        detail={
            "kb_id": data["kb_id"],
            "version": data["version"],
            "document_id": str(data["document_id"]),
        },
    )

    # 事务约定（BUG-1）：登记 + 审计在入队前显式提交，确保 worker 领取时文档行可见
    await db.commit()
    await task_service.enqueue_index_document(None, data["document_id"])

    return success(data=data)
