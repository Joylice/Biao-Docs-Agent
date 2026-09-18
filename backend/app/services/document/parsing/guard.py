"""三层防御 — Agent 工具白名单 + 调用时校验（T1.1/T1.3）.

Layer1：静态白名单（Agent 配置的 allowed_internal_tools）；
Layer2：运行时开关（tools_enabled = web_search_enabled 或 agent_tools_enabled）；
Layer3：executor 的 includes 校验（防止 LLM 越权调用其他 Agent 的工具）。

P1 阶段：所有 Agent 的 tools_enabled=False，即 Layer2 关闭，不触发任何工具调用。
"""

import logging

from app.services.document.parsing.registry import ParserAgentConfig, get_agent_config

logger = logging.getLogger(__name__)


def is_tool_call_allowed(
    agent_config: ParserAgentConfig,
    tool_name: str,
    tools_enabled: bool,
) -> bool:
    """三层防御校验：Agent 是否被允许调用某工具.

    Layer1：agent_config.allowed_internal_tools 含 tool_name；
    Layer2：agent_config.tools_enabled=True 且 tools_enabled（全局开关）为 True；
    Layer3：tool_name in allowed（includes 校验，防越权）。

    P1 阶段：tools_enabled 全部为 False → Layer2 关闭 → 所有工具调用被拒绝。
    """
    # Layer1 + Layer3 合并检查：tool_name 必须在该 Agent 的白名单内
    if tool_name not in agent_config.allowed_internal_tools:
        logger.warning(
            "工具越权：agent=%s 尝试调用 %s（不在白名单 %s）",
            agent_config.agent_id,
            tool_name,
            agent_config.allowed_internal_tools,
        )
        return False

    # Layer2：全局开关
    if not agent_config.tools_enabled:
        return False
    return tools_enabled


def get_allowed_tools_for_agent(
    agent_id: str,
    tools_enabled: bool,
) -> list[str]:
    """返回 Agent 在当前开关状态下允许调用的工具名列表.

    P1 阶段（tools_enabled=False）：所有 Agent 返回空列表（行为等价）。
    """
    cfg = get_agent_config(agent_id)
    if cfg is None:
        return []
    if not cfg.tools_enabled or not tools_enabled:
        return []
    return sorted(cfg.allowed_internal_tools)
