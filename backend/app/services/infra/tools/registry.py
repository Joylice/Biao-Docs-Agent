"""外部工具注册表 — 阶段白名单 + 绑定真源 + 动态 schema + 缓存.

核心职责：
- STAGE_TOOL_WHITELIST：流水线阶段 → 允许的工具类型集合（5 编制节点的 8 个 stage 全覆盖）；
- get_definitions()：查 stage_tool_bindings 获取该阶段已绑定的 enabled 外部工具 →
  组装 OpenAI function schema；缓存 30s TTL，键=stage_key；
- execute_external_tool()：查 DB 取 tool → 解密 key → call_external_tool；
- execute_bound_tool()：tool_id 字符串 → JSON 文本（各阶段工具 executor 复用）；
- invalidate()：清缓存。
"""

import json
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
# 5 个投标编制节点的全部 stage 均放行 http_search：
#   招标解析=parse+score / 方案大纲生成=outline / 方案生成=write+validate+consistency
#   / 方案评审=review / 方案导出=export —— 对齐前端「工具 ↔ 编制节点」绑定口径。
# 已接线注入点（get_definitions 的真实落地点）：
#   parse       → services/document/parsing/dispatch.py（多 Agent 取证轮）
#   outline     → agents/nodes/outline.py（generate_outline_node 取证前置）
#   write       → agents/tools.py::write_tool_preflight
#   validate    → agents/tools.py::validate_tool_recheck
#   consistency → services/proposal/consistency_service.py（取证前置）
#   review      → agents/nodes/review.py（auto_review_node：integrate → auto_review → review）
#                 仅首轮跑一轮（反馈回环绕过该节点，不重复调用 LLM）
# 尚无 LLM 调用点的 stage（绑定可存、运行期不触发）：
#   score  —— 评分点随 parse 一次产出，无独立 LLM 调用；
#   export —— 纯渲染导出，无 LLM 调用。
STAGE_TOOL_WHITELIST: dict[str, set[str]] = {
    "parse": {"http_search"},
    "score": {"http_search"},
    "outline": {"http_search"},
    "write": {"http_search"},
    "validate": {"http_search"},
    "consistency": {"http_search"},
    "review": {"http_search"},
    "export": {"http_search"},
}

# 30s TTL 缓存：stage_key → (timestamp, definitions)
_CACHE_TTL: float = 30.0
_definitions_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_key(stage_key: str) -> str:
    """构造缓存键."""
    return stage_key


async def get_definitions(
    stage_key: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取阶段可用的外部工具 OpenAI function schema 列表.

    唯一门槛：stage_key 在 STAGE_TOOL_WHITELIST 中且白名单含 http_search，且
    ``stage_tool_bindings`` 中存在指向「启用工具」的显式绑定 —— 「配置中心绑定即生效」，
    绑定本身即开关。

    2026-09-18 修正：此前另有一道 ``web_search_enabled`` 运行时闸，但该值在前端配置中心
    与 confirm-outline 请求体（ConfirmOutlineBody）中都没有入口 → 恒为 False →
    绑定永远不生效（外部搜索工具从未真正注入过任何阶段）。该死闸已删除。
    """
    # 阶段白名单
    allowed_types = STAGE_TOOL_WHITELIST.get(stage_key)
    if allowed_types is None or "http_search" not in allowed_types:
        return []

    # 缓存命中检查
    key = _cache_key(stage_key)
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


async def execute_bound_tool(
    name: str, arguments: dict[str, Any], project_id: str | None = None
) -> str:
    """按名执行已绑定外部工具（``name`` = tool_id 字符串），返回 JSON 文本.

    供各阶段 chat_with_tools 的 executor 复用：非法/未知 tool_id 不抛异常，
    统一回填 {"error": ...}，避免单个工具失败中断整轮取证。
    """
    try:
        tool_id = uuid.UUID(name)
    except (ValueError, AttributeError, TypeError):
        return json.dumps({"error": f"未知外部工具: {name}"}, ensure_ascii=False)
    result = await execute_external_tool(tool_id, arguments.get("query", ""), project_id)
    return json.dumps(result, ensure_ascii=False)


def invalidate() -> None:
    """清空外部工具定义缓存."""
    _definitions_cache.clear()
