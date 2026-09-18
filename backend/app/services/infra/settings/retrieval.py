"""检索参数持久化服务 — retrieval_configs 表读写.

单行配置（id=1），复用 security 的密钥三态契约与 Fernet 加密。
前端优先读 DB，回退 localStorage（向后兼容）。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.models.retrieval_config import RetrievalConfig
from app.schemas.settings import RetrievalConfigUpdate

from . import security as _security

_CONFIG_ID = 1  # 固定单行


async def get_retrieval_config_row(db: AsyncSession) -> RetrievalConfig | None:
    """读取单行配置（只读）."""
    result = await db.execute(select(RetrievalConfig).where(RetrievalConfig.id == _CONFIG_ID))
    return result.scalar_one_or_none()


async def get_retrieval_config_view(db: AsyncSession) -> dict[str, Any]:
    """GET 视图：参数明文 + rerank 密钥脱敏 + configured 标志.

    若 DB 无行（迁移后首次），返回默认值（与迁移 INSERT 一致）。
    """
    row = await get_retrieval_config_row(db)
    if row is None:
        return {
            "recall_top_k": 20,
            "similarity_threshold": 0.35,
            "hybrid_weight": 0.7,
            "rerank_enabled": True,
            "rerank_model": "dashscope/gte-rerank",
            "rerank_top_k": 5,
            "rerank_api_key": "",
            "rerank_configured": False,
        }
    rerank_key = _security._decrypt_or_empty(row.rerank_api_key_enc)
    return {
        "recall_top_k": row.recall_top_k,
        "similarity_threshold": row.similarity_threshold,
        "hybrid_weight": row.hybrid_weight,
        "rerank_enabled": row.rerank_enabled,
        "rerank_model": row.rerank_model or "",
        "rerank_top_k": row.rerank_top_k,
        "rerank_api_key": _security.mask_secret(rerank_key),
        "rerank_configured": bool(rerank_key),
    }


async def update_retrieval_config(db: AsyncSession, payload: RetrievalConfigUpdate) -> list[str]:
    """upsert 更新检索参数。密钥字段三态；返回变更字段名清单（供审计）.

    非密钥字段（recall_top_k 等）：None=保持、非 None=更新。
    rerank_api_key：None=保持、""=清除、非空=更新（加密入库，S-1 拒收脱敏串）。
    """
    row = await get_retrieval_config_row(db)
    if row is None:
        # 迁移后理论上总有 id=1 行，但做防御性 upsert
        row = RetrievalConfig(id=_CONFIG_ID)
        db.add(row)

    changed: list[str] = []

    if payload.recall_top_k is not None and payload.recall_top_k != row.recall_top_k:
        row.recall_top_k = payload.recall_top_k
        changed.append("recall_top_k")

    if (
        payload.similarity_threshold is not None
        and payload.similarity_threshold != row.similarity_threshold
    ):
        row.similarity_threshold = payload.similarity_threshold
        changed.append("similarity_threshold")

    if payload.hybrid_weight is not None and payload.hybrid_weight != row.hybrid_weight:
        row.hybrid_weight = payload.hybrid_weight
        changed.append("hybrid_weight")

    if payload.rerank_enabled is not None and payload.rerank_enabled != row.rerank_enabled:
        row.rerank_enabled = payload.rerank_enabled
        changed.append("rerank_enabled")

    if payload.rerank_model is not None:
        new_model = payload.rerank_model.strip() or None
        if new_model != row.rerank_model:
            row.rerank_model = new_model
            changed.append("rerank_model")

    if payload.rerank_top_k is not None and payload.rerank_top_k != row.rerank_top_k:
        row.rerank_top_k = payload.rerank_top_k
        changed.append("rerank_top_k")

    # rerank_api_key 密钥三态
    if payload.rerank_api_key is not None:
        new_key = payload.rerank_api_key.strip()
        _security._reject_masked_key("rerank_api_key", new_key)
        if new_key != _security._decrypt_or_empty(row.rerank_api_key_enc):
            changed.append("rerank_api_key")
        row.rerank_api_key_enc = encrypt_secret(new_key) if new_key else None

    await db.flush()
    return changed
