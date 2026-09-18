"""LLM 配置读写 — 全局配置存 llm_settings，密钥唯一真源为 llm_providers.

R1 重构（key 真源统一）：llm_settings 表仅承载全局配置（llm_model/llm_api_base/
llm_mock/embedding_api_base/embedding_model）；全部 API key（含自定义端点专用
密钥与 embedding 密钥）写入 llm_providers 行，其 *_key_enc 旧列废弃不读写。
三态契约语义不变（None=保持/""=清除/非空=更新），仅写入目标由 llm_settings
改为 llm_providers。本模块不含运行时缓存逻辑（缓存失效由 api 层在 commit
成功后调用 runtime.invalidate_runtime_cache）。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.models.llm_providers import ProviderRegistry
from app.models.llm_settings import LlmSetting
from app.schemas.settings import LlmSettingsUpdate

from . import security as _security

# payload 密钥字段 → llm_providers.prefix 映射
# （'custom' = 自定义端点专用密钥；embedding_api_key 按 embedding_model 前缀动态解析）
_PAYLOAD_KEY_TO_PREFIX: dict[str, str] = {
    "deepseek_api_key": "deepseek",
    "dashscope_api_key": "dashscope",
    "openai_api_key": "openai",
    "anthropic_api_key": "anthropic",
    "zhipu_api_key": "zhipu",
    "moonshot_api_key": "moonshot",
    "llm_api_key": "custom",
}


async def get_llm_settings(db: AsyncSession) -> LlmSetting | None:
    """读取单行配置（只读，不 commit）."""
    result = await db.execute(select(LlmSetting).limit(1))
    return result.scalar_one_or_none()


async def _load_provider_rows(db: AsyncSession) -> list[ProviderRegistry]:
    """读取 llm_providers 全量行（密钥唯一真源）."""
    result = await db.execute(select(ProviderRegistry))
    return list(result.scalars().all())


def _embedding_prefix(embedding_model: str | None) -> str | None:
    """取 embedding_model 的 provider 前缀（如 'dashscope/text-embedding-v3' → 'dashscope'）.

    无前缀返回 None（该模型无 providers 行可挂载密钥）。
    """
    if not embedding_model or "/" not in embedding_model:
        return None
    return embedding_model.split("/", 1)[0].lower()


async def get_settings_view(db: AsyncSession) -> dict[str, Any]:
    """GET 视图：密钥脱敏（源自 llm_providers 真源）+ configured 标志.

    全局配置字段仍读 llm_settings（无行回退 env 生效值）；
    embedding_api_key 按 embedding_model 前缀匹配 providers 行。
    """
    row = await get_llm_settings(db)
    by_prefix = {p.prefix: p for p in await _load_provider_rows(db)}

    def _plain(prefix: str | None) -> str | None:
        if not prefix:
            return None
        provider = by_prefix.get(prefix)
        if provider is None:
            return None
        return _security._decrypt_or_empty(provider.api_key_enc) or None

    deepseek = _plain("deepseek")
    dashscope = _plain("dashscope")
    openai = _plain("openai")
    anthropic = _plain("anthropic")
    zhipu = _plain("zhipu")
    moonshot = _plain("moonshot")
    llm_key = _plain("custom")
    embedding_model = (row.embedding_model if row is not None else None) or settings.embedding_model
    embedding_key = _plain(_embedding_prefix(embedding_model))
    return {
        "deepseek_api_key": _security.mask_secret(deepseek),
        "dashscope_api_key": _security.mask_secret(dashscope),
        "openai_api_key": _security.mask_secret(openai),
        "anthropic_api_key": _security.mask_secret(anthropic),
        "zhipu_api_key": _security.mask_secret(zhipu),
        "moonshot_api_key": _security.mask_secret(moonshot),
        "llm_model": (row.llm_model if row is not None else None) or settings.llm_model,
        "llm_api_base": (row.llm_api_base if row is not None else None) or "",
        "llm_api_key": _security.mask_secret(llm_key),
        "embedding_api_base": (
            (row.embedding_api_base if row is not None else None) or settings.embedding_api_base
        ),
        "embedding_model": embedding_model,
        "embedding_api_key": _security.mask_secret(embedding_key),
        "llm_mock": bool(row.llm_mock) if row is not None else settings.llm_mock,
        "deepseek_configured": bool(deepseek),
        "dashscope_configured": bool(dashscope),
        "openai_configured": bool(openai),
        "anthropic_configured": bool(anthropic),
        "zhipu_configured": bool(zhipu),
        "moonshot_configured": bool(moonshot),
        "llm_key_configured": bool(llm_key),
        "embedding_configured": bool(embedding_key),
    }


async def update_llm_settings(db: AsyncSession, payload: LlmSettingsUpdate) -> list[str]:
    """upsert 更新。密钥字段三态（W-5）：None=保持不变、""=清除、非空=更新；
    写入目标为 llm_providers 行（唯一 key 真源）：固定前缀字段按映射写入对应行，
    embedding_api_key 按（新）embedding_model 前缀匹配行、无前缀时跳过（无行可挂载）。
    embedding_api_base/llm_mock 必填全量。密钥加密入库，疑似脱敏串拒收（S-1），
    非空 base 做 SSRF 校验。返回变更字段名清单（供审计）。

    注意（W-1）：本函数不做缓存失效，由 api 层在 commit 成功后调用
    ``invalidate_runtime_cache()``。
    """
    row = await get_llm_settings(db)
    if row is None:
        row = LlmSetting()
        db.add(row)

    providers_by_prefix = {p.prefix: p for p in await _load_provider_rows(db)}

    async def _write_provider_key(field: str, prefix: str | None, raw: str) -> None:
        """三态写入 providers 行（密文加密；""=清空行密钥；变更记入 changed）."""
        new_plain = raw.strip()
        _security._reject_masked_key(field, new_plain)
        if not prefix:
            # 无目标行（如 embedding_model 无 provider 前缀）：密钥无处挂载，跳过写入
            return
        provider = providers_by_prefix.get(prefix)
        current = ""
        if provider is not None:
            current = _security._decrypt_or_empty(provider.api_key_enc)
        if new_plain == current:
            return
        if provider is None and not new_plain:
            # 无行且清空：无目标行可清，视为无变更
            return
        if provider is None:
            provider = ProviderRegistry(name=prefix, prefix=prefix)
            db.add(provider)
            providers_by_prefix[prefix] = provider
        provider.api_key_enc = encrypt_secret(new_plain) if new_plain else None
        changed.append(field)

    changed: list[str] = []

    if payload.deepseek_api_key is not None:
        await _write_provider_key("deepseek_api_key", "deepseek", payload.deepseek_api_key)

    if payload.dashscope_api_key is not None:
        await _write_provider_key("dashscope_api_key", "dashscope", payload.dashscope_api_key)

    if payload.openai_api_key is not None:
        await _write_provider_key("openai_api_key", "openai", payload.openai_api_key)

    if payload.anthropic_api_key is not None:
        await _write_provider_key("anthropic_api_key", "anthropic", payload.anthropic_api_key)

    if payload.zhipu_api_key is not None:
        await _write_provider_key("zhipu_api_key", "zhipu", payload.zhipu_api_key)

    if payload.moonshot_api_key is not None:
        await _write_provider_key("moonshot_api_key", "moonshot", payload.moonshot_api_key)

    # 自定义 LLM 主模型（三态：None=保持、""=清除回退 env、非空=更新）
    if payload.llm_model is not None:
        new_llm_model = payload.llm_model.strip() or None
        if new_llm_model != row.llm_model:
            changed.append("llm_model")
        row.llm_model = new_llm_model

    # 自定义 LLM 服务地址（三态；非空做 SSRF 校验）
    if payload.llm_api_base is not None:
        new_llm_base = payload.llm_api_base.strip() or None
        if new_llm_base:
            _security.validate_llm_api_base(new_llm_base)
        if new_llm_base != row.llm_api_base:
            changed.append("llm_api_base")
        row.llm_api_base = new_llm_base

    # 自定义端点专用密钥（三态，写 providers prefix='custom' 行）
    if payload.llm_api_key is not None:
        await _write_provider_key("llm_api_key", "custom", payload.llm_api_key)

    new_base = payload.embedding_api_base.strip() or None
    if new_base:
        _security.validate_embedding_api_base(new_base)
    if new_base != row.embedding_api_base:
        changed.append("embedding_api_base")
    row.embedding_api_base = new_base

    # embedding 模型名（非密钥，直接存明文）
    new_model = payload.embedding_model.strip() or None
    if new_model != row.embedding_model:
        changed.append("embedding_model")
    row.embedding_model = new_model

    # embedding API Key（三态）：按（新）embedding_model 前缀匹配 providers 行；
    # 模型名无 provider 前缀时无目标行，密钥写入跳过（与读取侧"无前缀→None"对称）
    if payload.embedding_api_key is not None:
        await _write_provider_key(
            "embedding_api_key", _embedding_prefix(new_model), payload.embedding_api_key
        )

    if bool(payload.llm_mock) != bool(row.llm_mock):
        changed.append("llm_mock")
    row.llm_mock = payload.llm_mock

    await db.flush()
    return changed
