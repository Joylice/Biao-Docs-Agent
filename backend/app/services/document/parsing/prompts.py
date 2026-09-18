"""提示词适配 — 只组数据，不直接拼字符串（T1.1/T1.2）.

职责：
- build_agent_context：根据 Agent 配置 + 窗口文本组装提示词渲染上下文；
- load_parser_agent_prompt：委托 PromptComposer 加载 parse_{agent_id}.yaml。

依赖方向：infra.prompt_loader → infra.prompt_composer（单向）。
本模块不直接依赖 llm_service（dispatch 负责 LLM 调用）。
"""

from typing import Any

from app.services.infra.prompt_loader import _composer


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
    """
    template_name = f"parse_{agent_id}"
    try:
        return _composer.compose(template_name, context)
    except Exception:
        # P1 回退：parse_score/parse_disqual/parse_norm/parse_validator 尚未创建时
        # 用旧 parse.yaml，行为与单次 LLM 调用等价（保证 G1 行为等价判据）
        return _composer.compose("parse", context)
