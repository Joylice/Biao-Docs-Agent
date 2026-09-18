"""外部工具注册表 — 阶段白名单 + 双闸校验 + 动态 schema + 缓存.

核心职责：
- STAGE_TOOL_WHITELIST：流水线阶段 → 允许的工具类型集合（parse/outline/write/validate）；
- get_definitions()：双闸校验（stage 在白名单 且 web_search_enabled）→ 查
  stage_tool_bindings 获取已绑定的 enabled 外部工具 → 组装 OpenAI function schema；
  缓存 30s TTL，键=f"{stage_key}:{web_search_enabled}"；
- execute_external_tool()：查 DB 取 tool → 解密 key → call_external_tool；
- invalidate()：清缓存。
"""

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.core.database import async_session_factory
from app.models.external_tool import ExternalTool, StageToolBinding
from app.services.infra.tools.http_tool_client import call_external_tool

logger = logging.getLogger(__name__)

# 阶段白名单：stage_key → 允许的工具类型集合
# parse/outline/write/validate 允许 http_search；consistency/review 为空集；
# score/integrate/export 不在白名单（无外部工具）
STAGE_TOOL_WHITELIST: dict[str, set[str]] = {
    "parse": {"http_search"},
    "outline": {"http_search"},
    "write": {"http_search"},
    "validate": {"http_search"},
    "consistency": set(),
    "review": set(),
}

# 30s TTL 缓存：(stage_key, web_search_enabled) → (timestamp, definitions)
_CACHE_TTL: float = 30.0
_definitions_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_key(stage_key: str, web_search_enabled: bool) -> str:
    """构造缓存键."""
    return f"{stage_key}:{web_search_enabled}"


async def get_definitions(
    stage_key: str,
    web_search_enabled: bool,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取阶段可用的外部工具 OpenAI function schema 列表.

    双闸校验：stage_key 必须在 STAGE_TOOL_WHITELIST 中且白名单含 http_search，
    同时 web_search_enabled 为 True；任一闸关闭返回空列表。
    """
    # 第一闸：阶段白名单
    allowed_types = STAGE_TOOL_WHITELIST.get(stage_key)
    if allowed_types is None or "http_search" not in allowed_types:
        return []

    # 第二闸：web_search 开关
    if not web_search_enabled:
        return []

    # 缓存命中检查
    key = _cache_key(stage_key, web_search_enabled)
    cached = _definitions_cache.get(key)
    if cached is not None:
        ts, defs = cached
        if time.monotonic() - ts < _CACHE_TTL:
            return defs

    # 查 DB 获取已绑定的 enabled 外部工具
    definitions: list[dict[str, Any]] = []
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(ExternalTool)
                .join(StageToolBinding, StageToolBinding.tool_id == ExternalTool.id)
                .where(StageToolBinding.stage_key == stage_key)
                .where(ExternalTool.enabled.is_(True))
            )
            tools = result.scalars().all()
            for tool in tools:
                if tool.tool_type not in allowed_types:
                    continue
                definitions.append(
                    {
                        "type": "function",
                        "function": {
                            "name": str(tool.id),
                            "description": f"外部搜索工具: {tool.name}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "搜索查询关键词",
                                    },
                                },
                                "required": ["query"],
                            },
                        },
                    }
                )
    except Exception:
        logger.warning("获取外部工具定义失败: stage=%s", stage_key, exc_info=True)
        return []

    # 写缓存
    _definitions_cache[key] = (time.monotonic(), definitions)
    return definitions


async def execute_external_tool(
    tool_id: uuid.UUID, query: str, project_id: str | None = None
) -> list[dict[str, Any]]:
    """执行外部工具调用：查 DB 取 tool → 解密 key → call_external_tool."""
    try:
        async with async_session_factory() as db:
            result = await db.execute(select(ExternalTool).where(ExternalTool.id == tool_id))
            tool = result.scalar_one_or_none()
            if tool is None:
                return [{"error": f"外部工具不存在: {tool_id}"}]
            if not tool.enabled:
                return [{"error": f"外部工具已禁用: {tool.name}"}]

            # 解密 API Key
            api_key: str | None = None
            if tool.api_key_enc:
                try:
                    api_key = decrypt_secret(tool.api_key_enc)
                except Exception:
                    logger.warning("外部工具 %s 密钥解密失败", tool.name)
                    api_key = None

            return await call_external_tool(tool, api_key, query)
    except Exception as exc:
        logger.warning("执行外部工具失败: tool_id=%s err=%s", tool_id, exc)
        return [{"error": f"外部工具执行失败: {exc}"}]


def invalidate() -> None:
    """清空外部工具定义缓存."""
    _definitions_cache.clear()
