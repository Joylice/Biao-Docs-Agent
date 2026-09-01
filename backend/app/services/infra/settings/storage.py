"""LLM 配置读写 — llm_settings 表 upsert（加密入库/三态契约/变更字段清单）.

从原 settings_service 拆分（第一轮模块拆分）：本模块只依赖 security 安全工具，
不含运行时缓存逻辑（缓存失效由 api 层在 commit 成功后调用 runtime.invalidate_runtime_cache）。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.models.llm_settings import LlmSetting
from app.schemas.settings import LlmSettingsUpdate

from . import security as _security


async def get_llm_settings(db: AsyncSession) -> LlmSetting | None:
    """读取单行配置（只读，不 commit）."""
    result = await db.execute(select(LlmSetting).limit(1))
    return result.scalar_one_or_none()


async def get_settings_view(db: AsyncSession) -> dict[str, Any]:
    """GET 视图：密钥脱敏 + configured 标志；未配置的 base/model/mock 展示 env 生效值."""
    row = await get_llm_settings(db)
    if row is None:
        return {
            "deepseek_api_key": "",
            "dashscope_api_key": "",
            "openai_api_key": "",
            "anthropic_api_key": "",
            "zhipu_api_key": "",
            "moonshot_api_key": "",
            "llm_model": settings.llm_model,
            "llm_api_base": "",
            "llm_api_key": "",
            "embedding_api_base": settings.embedding_api_base,
            "embedding_model": settings.embedding_model,
            "embedding_api_key": "",
            "llm_mock": settings.llm_mock,
            "deepseek_configured": False,
            "dashscope_configured": False,
            "openai_configured": False,
            "anthropic_configured": False,
            "zhipu_configured": False,
            "moonshot_configured": False,
            "llm_key_configured": False,
            "embedding_configured": False,
        }
    deepseek = _security._decrypt_or_empty(row.deepseek_api_key_enc)
    dashscope = _security._decrypt_or_empty(row.dashscope_api_key_enc)
    openai = _security._decrypt_or_empty(row.openai_api_key_enc)
    anthropic = _security._decrypt_or_empty(row.anthropic_api_key_enc)
    zhipu = _security._decrypt_or_empty(row.zhipu_api_key_enc)
    moonshot = _security._decrypt_or_empty(row.moonshot_api_key_enc)
    llm_key = _security._decrypt_or_empty(row.llm_api_key_enc)
    embedding_key = _security._decrypt_or_empty(row.embedding_api_key_enc)
    return {
        "deepseek_api_key": _security.mask_secret(deepseek),
        "dashscope_api_key": _security.mask_secret(dashscope),
        "openai_api_key": _security.mask_secret(openai),
        "anthropic_api_key": _security.mask_secret(anthropic),
        "zhipu_api_key": _security.mask_secret(zhipu),
        "moonshot_api_key": _security.mask_secret(moonshot),
        "llm_model": row.llm_model or settings.llm_model,
        "llm_api_base": row.llm_api_base or "",
        "llm_api_key": _security.mask_secret(llm_key),
        "embedding_api_base": row.embedding_api_base or settings.embedding_api_base,
        "embedding_model": row.embedding_model or settings.embedding_model,
        "embedding_api_key": _security.mask_secret(embedding_key),
        "llm_mock": row.llm_mock,
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
    embedding_api_base/llm_mock 必填全量。密钥加密入库，疑似脱敏串拒收（S-1），
    非空 base 做 SSRF 校验。返回变更字段名清单（供审计）。

    注意（W-1）：本函数不做缓存失效，由 api 层在 commit 成功后调用
    ``invalidate_runtime_cache()``。
    """
    row = await get_llm_settings(db)
    if row is None:
        row = LlmSetting()
        db.add(row)

    changed: list[str] = []

    if payload.deepseek_api_key is not None:
        new_deepseek = payload.deepseek_api_key.strip()
        _security._reject_masked_key("deepseek_api_key", new_deepseek)
        if new_deepseek != _security._decrypt_or_empty(row.deepseek_api_key_enc):
            changed.append("deepseek_api_key")
        row.deepseek_api_key_enc = encrypt_secret(new_deepseek) if new_deepseek else None

    if payload.dashscope_api_key is not None:
        new_dashscope = payload.dashscope_api_key.strip()
        _security._reject_masked_key("dashscope_api_key", new_dashscope)
        if new_dashscope != _security._decrypt_or_empty(row.dashscope_api_key_enc):
            changed.append("dashscope_api_key")
        row.dashscope_api_key_enc = encrypt_secret(new_dashscope) if new_dashscope else None

    # OpenAI API Key（密钥三态）
    if payload.openai_api_key is not None:
        new_openai = payload.openai_api_key.strip()
        _security._reject_masked_key("openai_api_key", new_openai)
        if new_openai != _security._decrypt_or_empty(row.openai_api_key_enc):
            changed.append("openai_api_key")
        row.openai_api_key_enc = encrypt_secret(new_openai) if new_openai else None

    # Anthropic API Key（密钥三态）
    if payload.anthropic_api_key is not None:
        new_anthropic = payload.anthropic_api_key.strip()
        _security._reject_masked_key("anthropic_api_key", new_anthropic)
        if new_anthropic != _security._decrypt_or_empty(row.anthropic_api_key_enc):
            changed.append("anthropic_api_key")
        row.anthropic_api_key_enc = encrypt_secret(new_anthropic) if new_anthropic else None

    # 智谱 AI API Key（密钥三态）
    if payload.zhipu_api_key is not None:
        new_zhipu = payload.zhipu_api_key.strip()
        _security._reject_masked_key("zhipu_api_key", new_zhipu)
        if new_zhipu != _security._decrypt_or_empty(row.zhipu_api_key_enc):
            changed.append("zhipu_api_key")
        row.zhipu_api_key_enc = encrypt_secret(new_zhipu) if new_zhipu else None

    # 月之暗面 API Key（密钥三态）
    if payload.moonshot_api_key is not None:
        new_moonshot = payload.moonshot_api_key.strip()
        _security._reject_masked_key("moonshot_api_key", new_moonshot)
        if new_moonshot != _security._decrypt_or_empty(row.moonshot_api_key_enc):
            changed.append("moonshot_api_key")
        row.moonshot_api_key_enc = encrypt_secret(new_moonshot) if new_moonshot else None

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

    # 自定义端点专用密钥（密钥三态，与 deepseek/dashscope 一致）
    if payload.llm_api_key is not None:
        new_llm_key = payload.llm_api_key.strip()
        _security._reject_masked_key("llm_api_key", new_llm_key)
        if new_llm_key != _security._decrypt_or_empty(row.llm_api_key_enc):
            changed.append("llm_api_key")
        row.llm_api_key_enc = encrypt_secret(new_llm_key) if new_llm_key else None

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

    # embedding API Key（密钥三态，与 deepseek/dashscope 一致）
    if payload.embedding_api_key is not None:
        new_emb_key = payload.embedding_api_key.strip()
        _security._reject_masked_key("embedding_api_key", new_emb_key)
        if new_emb_key != _security._decrypt_or_empty(row.embedding_api_key_enc):
            changed.append("embedding_api_key")
        row.embedding_api_key_enc = encrypt_secret(new_emb_key) if new_emb_key else None

    if bool(payload.llm_mock) != bool(row.llm_mock):
        changed.append("llm_mock")
    row.llm_mock = payload.llm_mock

    await db.flush()
    return changed
