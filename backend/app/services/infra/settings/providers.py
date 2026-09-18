"""LLM 服务商与模型路由服务 — CRUD + 密钥加密 + 脱敏视图.

参照 OpenMAIC provider-neutral routing：Provider 独立注册表 + 按阶段路由。
复用 settings.security 的密钥工具（mask_secret / _reject_masked_key / _validate_api_base）。
"""

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.core.exceptions import NotFoundError, ValidationError
from app.models.llm_providers import ModelRoute, ProviderRegistry
from app.schemas.settings import ProviderCreate, ProviderUpdate, RouteUpdate

from . import security as _security

# === Provider CRUD ===


async def list_providers(db: AsyncSession) -> list[dict[str, Any]]:
    """列出所有 provider（密钥脱敏）.

    custom 端点的实际模型名存在 llm_settings.llm_model（用户在配置中心填写），
    不在 providers.models 预置列表里；此处将其合并进 custom 行的 models 返回，
    使前端下拉框只有一个数据源（providers[].models），无需交叉读 llm_settings。
    """
    result = await db.execute(
        select(ProviderRegistry).order_by(ProviderRegistry.builtin.desc(), ProviderRegistry.name)
    )
    rows = result.scalars().all()

    # 读取 llm_settings.llm_model，合并到 custom provider 的 models 列表
    from .storage import get_llm_settings

    llm_row = await get_llm_settings(db)
    custom_model = (llm_row.llm_model if llm_row is not None else None) or ""

    views = []
    for p in rows:
        view = _provider_to_view(p)
        if p.prefix == "custom" and custom_model:
            models_list: list[str] = view["models"]
            if custom_model not in models_list:
                models_list.insert(0, custom_model)
        views.append(view)
    return views


async def get_provider_by_prefix(db: AsyncSession, prefix: str) -> ProviderRegistry | None:
    """按 prefix 查 provider（内部用，返回 ORM 对象）."""
    result = await db.execute(select(ProviderRegistry).where(ProviderRegistry.prefix == prefix))
    return result.scalar_one_or_none()


async def create_provider(db: AsyncSession, payload: ProviderCreate) -> dict[str, Any]:
    """新建 provider."""
    existing = await get_provider_by_prefix(db, payload.prefix)
    if existing:
        raise ValidationError(f"prefix '{payload.prefix}' 已存在")

    caps = _parse_capabilities(payload.capabilities)
    api_key_enc = None
    if payload.api_key:
        key = payload.api_key.strip()
        _security._reject_masked_key("api_key", key)
        if payload.api_base:
            _security._validate_api_base(payload.api_base, "api_base")
        api_key_enc = encrypt_secret(key)

    provider = ProviderRegistry(
        name=payload.name,
        prefix=payload.prefix,
        api_key_enc=api_key_enc,
        api_base=payload.api_base or None,
        cap_text=caps["text"],
        cap_embedding=caps["embedding"],
        cap_rerank=caps["rerank"],
        cap_vision=caps["vision"],
        builtin=False,
        enabled=True,
        models=payload.models,
    )
    db.add(provider)
    await db.flush()
    return _provider_to_view(provider)


async def update_provider(
    db: AsyncSession, provider_id: uuid.UUID, payload: ProviderUpdate
) -> dict[str, Any]:
    """更新 provider（密钥三态）."""
    result = await db.execute(select(ProviderRegistry).where(ProviderRegistry.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise NotFoundError("服务商")

    if payload.name is not None:
        provider.name = payload.name

    if payload.api_key is not None:
        new_key = payload.api_key.strip()
        _security._reject_masked_key("api_key", new_key)
        provider.api_key_enc = encrypt_secret(new_key) if new_key else None

    if payload.api_base is not None:
        new_base = payload.api_base.strip() or None
        if new_base:
            _security._validate_api_base(new_base, "api_base")
        provider.api_base = new_base

    if payload.enabled is not None:
        provider.enabled = payload.enabled

    if payload.capabilities is not None:
        caps = _parse_capabilities(payload.capabilities)
        provider.cap_text = caps["text"]
        provider.cap_embedding = caps["embedding"]
        provider.cap_rerank = caps["rerank"]
        provider.cap_vision = caps["vision"]

    if payload.models is not None:
        provider.models = payload.models

    await db.flush()
    return _provider_to_view(provider)


async def delete_provider(db: AsyncSession, provider_id: uuid.UUID) -> None:
    """删除 provider（内置不可删）."""
    result = await db.execute(select(ProviderRegistry).where(ProviderRegistry.id == provider_id))
    provider = result.scalar_one_or_none()
    if provider is None:
        raise NotFoundError("服务商")
    if provider.builtin:
        raise ValidationError("内置服务商不可删除，仅可禁用")
    await db.delete(provider)
    await db.flush()


def _provider_to_view(p: ProviderRegistry) -> dict[str, Any]:
    """Provider ORM → 前端视图（密钥脱敏）."""
    plain_key = _security._decrypt_or_empty(p.api_key_enc)
    models_list = [m.strip() for m in p.models.split(",")] if p.models else []
    return {
        "id": str(p.id),
        "name": p.name,
        "prefix": p.prefix,
        "apiKeyMasked": _security.mask_secret(plain_key),
        "configured": bool(plain_key),
        "apiBase": p.api_base or "",
        "defaultBase": p.default_base or "",
        "capabilities": {
            "text": p.cap_text,
            "embedding": p.cap_embedding,
            "rerank": p.cap_rerank,
            "vision": p.cap_vision,
        },
        "builtin": p.builtin,
        "enabled": p.enabled,
        "models": models_list,
    }


def _parse_capabilities(caps: list[str]) -> dict[str, bool]:
    """能力列表 → 四开关."""
    return {
        "text": "text" in caps,
        "embedding": "embedding" in caps,
        "rerank": "rerank" in caps,
        "vision": "vision" in caps,
    }


# === Model Route CRUD ===


async def list_routes(db: AsyncSession) -> list[dict[str, Any]]:
    """列出所有路由."""
    result = await db.execute(select(ModelRoute).order_by(ModelRoute.stage_key))
    rows = result.scalars().all()
    return [_route_to_view(r) for r in rows]


async def update_route(db: AsyncSession, stage_key: str, payload: RouteUpdate) -> dict[str, Any]:
    """更新单个路由."""
    result = await db.execute(select(ModelRoute).where(ModelRoute.stage_key == stage_key))
    route = result.scalar_one_or_none()
    if route is None:
        raise NotFoundError("路由")

    if payload.model is not None:
        route.model = payload.model.strip() or None
    if payload.fallback is not None:
        route.fallback = json.dumps(payload.fallback, ensure_ascii=False)
    if payload.thinking is not None:
        route.thinking = payload.thinking
    if payload.temperature is not None:
        route.temperature = payload.temperature
    if payload.max_tokens is not None:
        route.max_tokens = payload.max_tokens
    if payload.timeout is not None:
        route.timeout = payload.timeout
    if payload.hint is not None:
        route.hint = payload.hint
    if payload.enabled is not None:
        route.enabled = payload.enabled

    await db.flush()
    return _route_to_view(route)


def _route_to_view(r: ModelRoute) -> dict[str, Any]:
    """Route ORM → 前端视图."""
    fallback_list: list[str] = []
    if r.fallback:
        try:
            fallback_list = json.loads(r.fallback)
        except json.JSONDecodeError:
            fallback_list = []
    return {
        "id": str(r.id),
        "stageKey": r.stage_key,
        "stageName": r.stage_name,
        "nodeName": r.node_name,
        "model": r.model or "",
        "fallback": fallback_list,
        "thinking": r.thinking,
        "temperature": r.temperature,
        "maxTokens": r.max_tokens,
        "timeout": r.timeout,
        "hint": r.hint or "",
        "enabled": r.enabled,
    }
