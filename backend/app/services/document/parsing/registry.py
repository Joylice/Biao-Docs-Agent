"""Agent 注册表 — 4 Agent 配置（T1.1）.

ParserAgentConfig：单个 Agent 的配置（agent_id、产出字段、LLM schema、
是否允许工具取证、提示词模板名）。
PARSER_AGENTS：4 个 Agent 的有序列表。

P1 阶段：工具默认关闭（agent_tools_enabled=False），行为与旧单次 LLM 等价。
P2 阶段：validator 上线；工具白名单仍默认关，需 web_search_enabled=True 才开启。

依赖方向：仅依赖 results.AgentResult（类型引用），无 service 层依赖。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParserAgentConfig:
    """单个解析 Agent 配置."""

    agent_id: str
    # 产出字段名（对应 ParsedTender 属性）
    output_fields: list[str]
    # LLM JSON schema（properties + required）
    schema_properties: dict[str, Any]
    schema_required: list[str]
    # 提示词 YAML 模板名（如 "parse_score"）
    prompt_template: str
    # 是否允许该 Agent 使用工具取证（Layer1 白名单）
    tools_enabled: bool = False
    # 该 Agent 允许的内部工具名集合
    allowed_internal_tools: set[str] = field(default_factory=set)
    # 描述（文档用途）
    description: str = ""


# ── LLM JSON Schema 片段（Agent 各自只管自己产出的字段）──

_SCORE_POINT_ITEM = {
    "type": "object",
    "properties": {
        "clause_no": {"type": "string"},
        "item": {"type": "string"},
        "score": {"type": "number"},
        "criteria": {"type": "string"},
        "is_star": {"type": "boolean"},
        "risk_level": {"type": "string"},
    },
    "required": ["clause_no", "item"],
}

_DISQUAL_ITEM = {
    "type": "object",
    "properties": {
        "clause_no": {"type": "string"},
        "title": {"type": "string"},
        "risk_category": {"type": "string"},
        "severity": {"type": "string"},
        "recommendation": {"type": "string"},
    },
    "required": ["clause_no", "title"],
}

_FORMAT_REQ_ITEM = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "requirement": {"type": "string"},
    },
    "required": ["category", "requirement"],
}

_GLOSSARY_ITEM = {
    "type": "object",
    "properties": {
        "term": {"type": "string"},
        "canonical": {"type": "string"},
        "desc": {"type": "string"},
    },
    "required": ["term", "canonical"],
}

# score_agent 额外产出 project_name / tender_no
_SCORE_EXTRA_PROPS = {
    "project_name": {"type": "string"},
    "tender_no": {"type": "string"},
}


# ── 4 Agent 配置 ──

PARSER_AGENTS: list[ParserAgentConfig] = [
    ParserAgentConfig(
        agent_id="score_agent",
        output_fields=["score_points", "project_name", "tender_no"],
        schema_properties={
            "score_points": {"type": "array", "items": _SCORE_POINT_ITEM},
            "project_name": {"type": "string"},
            "tender_no": {"type": "string"},
        },
        schema_required=["score_points"],
        prompt_template="parse_score",
        tools_enabled=False,
        allowed_internal_tools={"search_tender_text"},
        description="评分点提取（含项目名称/编号）— 核心交付物",
    ),
    ParserAgentConfig(
        agent_id="disqual_agent",
        output_fields=["disqualification_clauses"],
        schema_properties={
            "disqualification_clauses": {"type": "array", "items": _DISQUAL_ITEM},
        },
        schema_required=["disqualification_clauses"],
        prompt_template="parse_disqual",
        tools_enabled=False,
        allowed_internal_tools={"search_tender_text"},
        description="废标/红线条款提取",
    ),
    ParserAgentConfig(
        agent_id="norm_agent",
        output_fields=["format_requirements", "glossary"],
        schema_properties={
            "format_requirements": {"type": "array", "items": _FORMAT_REQ_ITEM},
            "glossary": {"type": "array", "items": _GLOSSARY_ITEM},
        },
        schema_required=["format_requirements", "glossary"],
        prompt_template="parse_norm",
        tools_enabled=False,
        allowed_internal_tools={"search_tender_text"},
        description="格式要求 + 术语表提取（合并 Agent）",
    ),
    ParserAgentConfig(
        agent_id="validator_agent",
        output_fields=[],
        schema_properties={
            "warnings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "message": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                    "required": ["type", "message"],
                },
            }
        },
        schema_required=["warnings"],
        prompt_template="parse_validator",
        tools_enabled=False,
        allowed_internal_tools={"search_tender_text", "get_agent_results"},
        description="交叉校验（只产 warnings，不覆盖上游 data）",
    ),
]


def get_agent_config(agent_id: str) -> ParserAgentConfig | None:
    """按 agent_id 查配置，未命中返回 None."""
    for cfg in PARSER_AGENTS:
        if cfg.agent_id == agent_id:
            return cfg
    return None
