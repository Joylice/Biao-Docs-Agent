"""内置解析工具 — search_tender_text / get_agent_results / execute_parser_tool（T1.3）.

P1 阶段：工具默认关闭（Agent 的 tools_enabled=False → guard 拒绝 → 不触发）。
P2 阶段：工具上线，但仍需 web_search_enabled=True 才走 chat_with_tools。

设计要点：
- make_tool_definitions：按 allowed_tools 列表组装 OpenAI function schema；
- execute_parser_tool：调度执行，经 guard 三层防御校验；
- search_tender_text：全文搜索（突破 40k 窗口限制），注入闭包文本无模块级缓存；
- get_agent_results：返回前序 Agent 的输出（仅 validator 可用）。

依赖方向：parsing.guard / parsing.registry → 本模块（反向依赖由 dispatch 注入）。
"""

import logging
from typing import Any

from app.services.document.parsing.guard import is_tool_call_allowed
from app.services.document.parsing.registry import get_agent_config

logger = logging.getLogger(__name__)


def make_tool_definitions(
    allowed_tools: list[str],
    tender_window: str,
    prior_results: dict[str, Any],
) -> list[dict[str, Any]]:
    """组装 Agent 可用的 OpenAI function schema 列表.

    Args:
        allowed_tools: guard 返回的允许工具名列表；
        tender_window: 闭包注入的全文窗口（供 search_tender_text 使用）；
        prior_results: 前序 Agent 结果（供 get_agent_results 使用）。

    P1 阶段：allowed_tools 始终为空列表 → 返回空 → chat_with_tools 不触发。
    """
    definitions: list[dict[str, Any]] = []
    for tool_name in allowed_tools:
        if tool_name == "search_tender_text":
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "search_tender_text",
                        "description": "在招标文件全文中搜索关键词（突破窗口截取限制）",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "搜索关键词",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )
        elif tool_name == "get_agent_results":
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "get_agent_results",
                        "description": "获取前序 Agent 的提取结果（仅 validator 可用）",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "description": "要查询的字段名（如 score_points）",
                                },
                            },
                            "required": ["field"],
                        },
                    },
                }
            )
    return definitions


async def execute_parser_tool(
    name: str,
    arguments: dict[str, Any],
    agent_id: str,
    tender_window: str = "",
    prior_results: dict[str, Any] | None = None,
    tools_enabled: bool = False,
) -> str:
    """执行解析工具（经三层防御校验）.

    Args:
        name: 工具名（search_tender_text / get_agent_results）；
        arguments: LLM 解析出的参数 dict；
        agent_id: 调用方 Agent ID（用于 guard 校验）；
        tender_window: 闭包注入的全文（dispatch 在调用前注入）；
        prior_results: 前序 Agent 结果（dispatch 在调用前注入）；
        tools_enabled: 全局工具开关（P1=False）。

    Returns:
        str: 工具执行结果（回填给 LLM 的文本）。

    Layer3 校验：is_tool_call_allowed 检查 agent → tool 白名单 + 全局开关。
    """
    cfg = get_agent_config(agent_id)
    if cfg is None:
        return f"工具执行失败: 未知 Agent {agent_id}"

    # Layer1 + Layer2 + Layer3 三层防御
    if not is_tool_call_allowed(cfg, name, tools_enabled):
        logger.warning("工具调用被防御层拒绝: agent=%s tool=%s", agent_id, name)
        return f"工具 {name} 不允许在当前 Agent 或开关状态下使用"

    prior = prior_results or {}

    if name == "search_tender_text":
        return _search_tender_text(tender_window, arguments.get("query", ""))
    elif name == "get_agent_results":
        return _get_agent_results(prior, arguments.get("field", ""))
    else:
        return f"未知工具: {name}"


def _search_tender_text(full_text: str, query: str) -> str:
    """在招标全文中搜索关键词，返回匹配段落（≤2000 字符）.

    无模块级缓存 — 每次调用使用闭包注入的 full_text。
    """
    if not full_text or not query:
        return "搜索失败：缺少全文或查询词"

    idx = full_text.find(query)
    if idx == -1:
        # 模糊搜索：取每个字符的 find，回退到空
        return f"未在招标文件全文中找到关键词「{query}」"

    # 返回匹配位置 ±1000 字符的上下文
    start = max(0, idx - 1000)
    end = min(len(full_text), idx + len(query) + 1000)
    excerpt = full_text[start:end]
    return f"在位置 {idx} 找到「{query}」，上下文：\n{excerpt}"


def _get_agent_results(prior_results: dict[str, Any], field: str) -> str:
    """返回前序 Agent 的输出字段（仅 validator 可用，guard 已校验）."""
    if not field:
        return "查询失败：缺少 field 参数"
    val = prior_results.get(field)
    if val is None:
        return f"前序结果中无字段 {field}"
    if isinstance(val, list):
        return f"{field}（共 {len(val)} 条）：\n{val!r}"
    return f"{field}: {val!r}"
