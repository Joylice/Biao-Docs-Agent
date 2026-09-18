"""外部工具取证前置 — 各阶段 LLM 调用前的统一注入点（5 编制节点口径）.

真源：``stage_tool_bindings``（配置中心「工具 ↔ 编制节点」的显式绑定，「绑定即生效」）。
``prefetch_external_evidence`` 在目标 stage 存在已启用绑定工具时，先跑一轮 tool calling
让 LLM 自主决定检索词，把检索结果**追加**到 user_prompt 尾部，交回调用方继续原有
JSON schema 流程 —— 不改动调用方任何输出格式约束。

不变量（务必保持，否则会静默改变存量行为）：
- **无绑定 → 原样返回**（一次 LLM 都不多发），未绑定工具的项目行为零变更；
- mock 模式直接短路（与节点层 ``is_mock_enabled`` 守卫一致，保证 E2E 确定性）；
- 任何异常（含开关读取失败）一律降级为「原样返回」—— 取证失败绝不阻塞编制主链路。
"""

import logging
from typing import Any

from app.services.infra import settings_service

logger = logging.getLogger(__name__)

# 取证意图提示词：只决定「要不要检索 / 检索什么」，不参与各阶段的业务输出
_EXTRACT_SYSTEM_PROMPT = (
    "你是投标方案资料检索助手。请根据任务描述与上下文判断是否需要联网检索外部资料"
    "（行业标准、规范条文、同类工程案例、厂商参数等）。"
    "需要时调用提供的搜索工具，查询词要具体；不需要时直接回复「无需检索」，不要调用工具。"
)

# 追加块标题（供人工排查「本段内容来自外部工具」）
EVIDENCE_HEADING = "## 联网检索取证结果（外部工具）"

# 送模型判断检索方向的上下文截断长度：只为「决定检索什么」，无需全文
_CONTEXT_EXCERPT_CHARS = 2000


async def prefetch_external_evidence(
    stage_key: str,
    system_prompt: str,
    user_prompt: str,
    project_id: str | None = None,
    *,
    intent: str = "",
    max_rounds: int = 2,
) -> tuple[str, str]:
    """按 stage 绑定情况为提示词追加外部检索证据.

    Args:
        stage_key: 流水线阶段（parse/score/outline/write/validate/consistency/review/export）；
        system_prompt: 调用方原始系统提示词（本函数不改动，原样透传）；
        user_prompt: 调用方原始用户提示词（命中时在尾部追加证据块）；
        project_id: 项目 ID（外部工具执行上下文，可空）；
        intent: 取证意图描述，用于让 LLM 判断检索方向；
        max_rounds: tool calling 最大轮数.

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)。无绑定 / 无命中 / 异常时与入参一致。
    """
    try:
        if await settings_service.is_mock_enabled():
            return system_prompt, user_prompt
    except Exception:
        # 开关读取失败按「关闭取证」处理：宁可少一次联网，不可阻塞编制
        logger.warning("读取 mock 开关失败（跳过外部工具取证）: stage=%s", stage_key, exc_info=True)
        return system_prompt, user_prompt

    from app.services.infra.tools.registry import execute_bound_tool, get_definitions
    from app.services.llm.llm_service import chat_with_tools

    tools = await get_definitions(stage_key, project_id)
    if not tools:
        return system_prompt, user_prompt

    async def _executor(name: str, arguments: dict[str, Any]) -> str:
        return await execute_bound_tool(name, arguments, project_id)

    context = (user_prompt or "")[:_CONTEXT_EXCERPT_CHARS]
    try:
        _text, calls = await chat_with_tools(
            system_prompt=_EXTRACT_SYSTEM_PROMPT,
            user_prompt=f"## 任务\n{intent or stage_key}\n\n## 上下文（截断）\n{context}",
            tools=tools,
            executor=_executor,
            max_rounds=max_rounds,
            stage_key=stage_key,
            project_id=project_id,
        )
    except Exception:
        logger.warning("外部工具取证失败（降级原提示词）: stage=%s", stage_key, exc_info=True)
        return system_prompt, user_prompt

    blocks: list[str] = []
    for call in calls:
        result = str(call.get("result", "") or "")
        if not result:
            continue
        query = (call.get("arguments") or {}).get("query", "")
        blocks.append(f"### 检索「{query}」\n{result}")
    if not blocks:
        return system_prompt, user_prompt

    augmented = f"{user_prompt}\n\n---\n\n{EVIDENCE_HEADING}\n" + "\n\n".join(blocks)
    return system_prompt, augmented
