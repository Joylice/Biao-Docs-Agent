"""提示词适配 — 只组数据，不直接拼字符串（T1.1/T1.2）.

职责：
- build_agent_context：根据 Agent 配置 + 窗口文本组装提示词渲染上下文；
- load_parser_agent_prompt：委托 PromptComposer 加载 parse_{agent_id}.yaml。

依赖方向：infra.prompt_loader → infra.prompt_composer（单向）。
本模块不直接依赖 llm_service（dispatch 负责 LLM 调用）。
"""

import logging
from typing import Any

from app.core.exceptions import BizError
from app.services.infra.prompt_loader import _composer

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


def load_parser_agent_prompt(
    agent_id: str,
    context: dict[str, Any],
) -> tuple[str, str]:
    """加载解析 Agent 提示词（委托 PromptComposer）.

    模板文件：prompts/parse_{agent_id}.yaml
    （score_agent → parse_score.yaml, validator_agent → parse_validator.yaml, …）

    向后兼容：P1 阶段如果 parse_{agent_id}.yaml 不存在，回退到旧 parse.yaml
    （行为等价，保证不 break 旧测试）。

    2026-09-18 收窄异常口径：原实现 `except Exception:` 会吞掉**一切**异常
    （含 YAML 语法错、DSL 字段名错、模板名校验失败），静默回退旧模板且零日志 ——
    表现为「改了提示词但模型行为没变」，排查成本极高。
    现改为**只兜「模板不存在」（BizError 5009）**，其他异常一律上抛；
    且回退时打 warning 留痕，不再静默。
    """
    template_name = f"parse_{agent_id}"
    try:
        return _composer.compose(template_name, context)
    except BizError as e:
        if e.code != 5009:
            raise
        # 仅「模板文件不存在」走回退（P1 过渡：parse_{agent_id}.yaml 未创建时用旧 parse.yaml）
        logger.warning(
            "解析 Agent 模板 %s.yaml 不存在，回退 parse.yaml（agent=%s）",
            template_name,
            agent_id,
            exc_info=True,
        )
        return _composer.compose("parse", context)
