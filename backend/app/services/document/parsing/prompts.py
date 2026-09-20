"""提示词适配 — 只组数据，不直接拼字符串（T1.1/T1.2）.

职责：
- build_agent_context：根据 Agent 配置 + 窗口文本组装提示词渲染上下文；
- load_agent_skill_prompt：S3/S5 解析 skill 契约（真源 = skills/<name>/SKILL.md +
  用户 DB 覆盖），返回三元组带 skill 名归因；未命中由调用方兜底旧 parse.yaml。

S6 收敛（2026-09-18）：load_parser_agent_prompt（per-agent YAML parse_<agent_id>.yaml
二级回退）已删除 —— 四份 parse_*.yaml 真源已迁 backend/skills/<name>/SKILL.md，
兜底只保留最底层 parse.yaml（dispatch 直接调 load_parse_prompt）。
本模块不直接依赖 llm_service（dispatch 负责 LLM 调用）。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_agent_context(
    agent_id: str,
    tender_window: str,
    prior_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装单个 Agent 的提示词渲染上下文.

    Args:
        agent_id: Agent 标识（如 "score_agent"）。
        tender_window: 经 select_parse_window 截取后的招标文本。
        prior_results: 前序 Agent 已完成的结果（validator 需要）。

    Returns:
        dict: 供 YAML 模板 str.format / DSL 条件渲染的上下文。
    """
    ctx: dict[str, Any] = {"tender_text": tender_window}

    if prior_results:
        # validator Agent 需要前序 Agent 的结果做交叉校验
        ctx["prior_results"] = _format_prior_results(prior_results)

    return ctx


async def load_agent_skill_prompt(
    agent_id: str,
    stage_key: str,
    context: dict[str, Any],
) -> tuple[str, str, str | None] | None:
    """S3/S5：解析该 Agent 的 skill 契约（内置 `parse_<x>` / 用户覆盖）并带出 skill 名.

    返回 (system_prompt, user_prompt, skill_name)；skill_name 供 dispatch 透传
    llm_usage_log 归因（S5）。未命中返回 None，由调用方回退旧 YAML —— **不抛异常**，
    对齐多 Agent 解析「单 Agent 失败不阻断」的既有降级契约。
    """
    from app.services.skills.consume import resolve_agent_skill_prompt

    try:
        hit = await resolve_agent_skill_prompt(agent_id, stage_key, context, db=None)
    except Exception:
        logger.warning("Agent %s 的 skill 契约解析异常，回退 YAML", agent_id, exc_info=True)
        return None
    if hit is None:
        return None
    system_prompt, user_prompt, contract = hit
    return system_prompt, user_prompt, contract.name


def _format_prior_results(prior: dict[str, Any]) -> str:
    """将前序 Agent 结果格式化为提示词可注入的文本片段."""
    parts: list[str] = []
    for field_name, val in prior.items():
        if isinstance(val, list) and val:
            parts.append(f"## {field_name}（共 {len(val)} 条）")
            for i, item in enumerate(val, 1):
                if isinstance(item, dict):
                    summary = " | ".join(f"{k}: {v}" for k, v in item.items() if v)
                    parts.append(f"  {i}. {summary}")
                else:
                    parts.append(f"  {i}. {item}")
            parts.append("")
        elif isinstance(val, str) and val:
            parts.append(f"## {field_name}\n{val}\n")
    return "\n".join(parts) if parts else "（无前序结果）"
