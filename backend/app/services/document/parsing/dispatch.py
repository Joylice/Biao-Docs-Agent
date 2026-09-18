"""并行调度 — 两段式 + Semaphore + 降级（T1.1/T1.4）.

编排流程：
  Stage A（3 提取 Agent 并行，Semaphore(3)）
  → Stage B（validator Agent 后置，需前序结果）

降级策略：
  - 单 Agent 失败不抛出，记 warnings 继续；
  - 多数失败（≥2/3 提取 Agent 失败）→ 回退旧 parse_tender_with_llm 单次调用；
  - validator 失败 → 不阻断，warnings 填「交叉校验未完成」。

P1 阶段：Agent 提示词 YAML 未就绪 → load_parser_agent_prompt 回退旧 parse.yaml，
行为与旧单次 LLM 等价。dispatch 入口被 worker/tasks.py 调用（但 worker 仍可走旧路径
直到 T1.5 接线）。

依赖方向：parsing.windows / parsing.registry / parsing.prompts /
parsing.guard / parsing.results → infra.llm_service（单向）。
"""

import asyncio
import logging
import time
from typing import Any

from app.core.redact import redact
from app.services.document.parsing.guard import get_allowed_tools_for_agent
from app.services.document.parsing.prompts import (
    build_agent_context,
    load_agent_skill_prompt,
    load_parser_agent_prompt,
)
from app.services.document.parsing.registry import PARSER_AGENTS, ParserAgentConfig
from app.services.document.parsing.results import AgentResult, ParsedTender, merge_agent_results
from app.services.document.parsing.windows import select_parse_window

logger = logging.getLogger(__name__)

# ── 命名常量 ──
MAX_CONCURRENT_AGENTS = 3
# 提取 Agent 数量（Stage A）
NUM_EXTRACTION_AGENTS = 3
# 降级阈值：失败的提取 Agent 数 ≥ 此值则回退
DEGRADE_THRESHOLD = 2


async def _run_single_agent(
    config: ParserAgentConfig,
    tender_window: str,
    prior_results: dict[str, Any] | None,
    tools_enabled: bool,
    project_id: str | None = None,
) -> AgentResult:
    """执行单个 Agent：加载提示词 → 调 LLM → 返回 AgentResult."""
    from app.services.llm.llm_service import call_llm_with_schema

    start = time.monotonic()
    context = build_agent_context(config.agent_id, tender_window, prior_results)

    # S3 新路径：skill 契约注册表优先（内置 parse_<x> / 用户覆盖），未命中回退旧 YAML。
    # S5：命中时带出 skill_name，透传 LLM 调用落 llm_usage_log（归因到具体准则）。
    hit = await load_agent_skill_prompt(config.agent_id, "parse", context)
    skill_name: str | None = None
    if hit is not None:
        system_prompt, user_prompt, skill_name = hit
    else:
        try:
            system_prompt, user_prompt = load_parser_agent_prompt(config.agent_id, context)
        except Exception as e:
            logger.warning("Agent %s 提示词加载失败，回退旧 parse.yaml: %s", config.agent_id, e)
            # 回退：用旧 parse.yaml 作为提示词
            from app.services.infra.prompt_loader import load_parse_prompt

            system_prompt, user_prompt = load_parse_prompt(redact(tender_window))

    # 组装 response_format
    response_format: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": f"parse_{config.agent_id}",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": config.schema_properties,
                "required": config.schema_required,
            },
        },
    }

    # 内置解析工具：受 guard 三层防御 + tools_enabled 总开关约束
    allowed_tools = get_allowed_tools_for_agent(config.agent_id, tools_enabled)
    # 外部搜索工具：真源 = stage_tool_bindings 显式绑定，与内置工具开关无关
    # （配置中心「绑定即生效」；parse 即「招标解析」编制节点）
    from app.services.infra.tools.registry import get_definitions as get_ext_definitions

    ext_tools = await get_ext_definitions("parse", project_id)

    try:
        if allowed_tools or ext_tools:
            # 两段式（先 chat_with_tools 取证，再 call_llm_with_schema 出 JSON）
            result = await _run_agent_with_tools(
                config,
                system_prompt,
                user_prompt,
                response_format,
                allowed_tools,
                tender_window,
                prior_results or {},
                project_id,
                ext_tools,
                skill_name,
            )
        else:
            # P1：直接 JSON schema 调用（行为等价旧 parse_tender_with_llm）
            result = await call_llm_with_schema(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=response_format,
                stage_key="parse",
                project_id=project_id,
                skill_name=skill_name,
            )
    except Exception as e:
        logger.warning("Agent %s 执行失败: %s", config.agent_id, e)
        return AgentResult(
            agent_id=config.agent_id,
            data={},
            success=False,
            elapsed_s=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start

    # 提取 Agent 产出的字段
    agent_data: dict[str, Any] = {}
    for field_name in config.output_fields:
        val = result.get(field_name)
        if val is not None:
            agent_data[field_name] = val

    # validator Agent 的 warnings 单独处理
    warnings: list[dict[str, Any]] = []
    if config.agent_id == "validator_agent":
        raw_warnings = result.get("warnings", [])
        for w in raw_warnings:
            if isinstance(w, dict):
                w = {**w, "agent_id": config.agent_id}
            warnings.append(w)

    return AgentResult(
        agent_id=config.agent_id,
        data=agent_data,
        warnings=warnings,
        elapsed_s=elapsed,
        success=True,
    )


async def _run_agent_with_tools(
    config: ParserAgentConfig,
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any],
    allowed_tools: list[str],
    tender_window: str,
    prior_results: dict[str, Any],
    project_id: str | None,
    ext_tools: list[dict[str, Any]] | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """两段式执行：Stage A chat_with_tools 取证 → Stage B call_llm_with_schema JSON.

    进入条件：内置解析工具放行（guard + tools_enabled）**或**该 stage 绑定了外部搜索
    工具；两者皆无时调用方走单段 JSON schema 分支（行为等价旧单次调用）。
    skill_name：S5 归因透传（Stage A/B 两段落库同一条准则名）。
    """
    from app.services.infra.tools.parser_tools import execute_parser_tool, make_tool_definitions
    from app.services.infra.tools.registry import execute_bound_tool
    from app.services.llm.llm_service import call_llm_with_schema, chat_with_tools

    builtin_defs = make_tool_definitions(allowed_tools, tender_window, prior_results)
    builtin_names = {d["function"]["name"] for d in builtin_defs}
    tools = builtin_defs + list(ext_tools or [])

    async def _executor(name: str, arguments: dict[str, Any]) -> str:
        # 内置工具经 guard 三层防御；外部工具（name = tool_id）走绑定工具执行器
        if name in builtin_names:
            # 修复：原实现漏传 tender_window / prior_results，
            # 致 search_tender_text 恒拿不到全文（永远返回「缺少全文或查询词」）
            return await execute_parser_tool(
                name, arguments, config.agent_id, tender_window, prior_results
            )
        return await execute_bound_tool(name, arguments, project_id)

    # Stage A：取证（≤2 轮）
    _text, _calls = await chat_with_tools(
        system_prompt,
        user_prompt,
        tools,
        _executor,
        max_rounds=2,
        stage_key="parse",
        project_id=project_id,
        skill_name=skill_name,
    )

    # Stage B：JSON schema 输出
    return await call_llm_with_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=response_format,
        stage_key="parse",
        project_id=project_id,
        skill_name=skill_name,
    )


async def parse_tender_multi_agent(
    text: str,
    tools_enabled: bool = False,
    project_id: str | None = None,
) -> ParsedTender:
    """多 Agent 并行解析招标文件.

    流程：
    1. select_parse_window 截取窗口；
    2. 3 个提取 Agent 并行（Semaphore 限流）；
    3. validator Agent 后置（需前序结果）；
    4. 合并结果。

    降级：≥2 个提取 Agent 失败 → 回退旧 parse_tender_with_llm。
    """
    tender_window = select_parse_window(text)

    # Stage A：3 个提取 Agent 并行
    extraction_configs = [c for c in PARSER_AGENTS if c.agent_id != "validator_agent"]
    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

    async def _run_with_sem(cfg: ParserAgentConfig) -> AgentResult:
        async with sem:
            return await _run_single_agent(cfg, tender_window, None, tools_enabled, project_id)

    extraction_results = await asyncio.gather(*[_run_with_sem(cfg) for cfg in extraction_configs])

    # 降级判定
    failed_count = sum(1 for r in extraction_results if not r.success)
    if failed_count >= DEGRADE_THRESHOLD:
        logger.warning(
            "多数提取 Agent 失败（%d/%d），回退旧单次 LLM 解析",
            failed_count,
            len(extraction_configs),
        )
        return await _fallback_single_agent(text, project_id)

    # Stage B：validator 后置
    prior_data: dict[str, Any] = {}
    for r in extraction_results:
        if r.success:
            prior_data.update(r.data)

    validator_result = await _run_single_agent(
        next(c for c in PARSER_AGENTS if c.agent_id == "validator_agent"),
        tender_window,
        prior_data,
        tools_enabled,
        project_id,
    )

    all_results = [*extraction_results, validator_result]
    return merge_agent_results(all_results)


async def _fallback_single_agent(text: str, project_id: str | None) -> ParsedTender:
    """降级路径：回退旧 parse_tender_with_llm 单次调用.

    P1 阶段：旧 parse_tender_with_llm 仍可用（门面 re-export 保留）。
    """
    # 延迟 import 避免循环依赖
    from app.services.document.parse_service import parse_tender_with_llm

    parsed = await parse_tender_with_llm(text)
    # 补 warnings 标注降级
    parsed.warnings = [{"type": "degraded", "message": "多 Agent 失败，回退单次 LLM 解析"}]
    return parsed
