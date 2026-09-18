"""解析结果数据结构 — 自 parse_service 下沉（T1.1）.

ParsedTender：招标解析最终结果（门面层与 worker 兼容的 dataclass）。
AgentResult：单个 Agent 的输出（含 agent_id、data、warnings、elapsed_s）。
merge_agent_results：将多 Agent 结果按字段合并为 ParsedTender。

依赖方向：无外部依赖（纯 dataclass + 合并逻辑）。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedTender:
    """招标解析结果."""

    score_points: list[dict[str, Any]]
    project_name: str | None = None
    tender_no: str | None = None
    # 施组/技术方案格式要求（排版规范）：[{category, requirement}]，存 Document.meta
    format_requirements: list[dict[str, Any]] = field(default_factory=list)
    # 阶段 E2 术语表：[{term, canonical, desc}]，存 Document.meta.glossary
    glossary: list[dict[str, Any]] = field(default_factory=list)
    # 阶段 H 废标/红线条款：[{clause_no, title, risk_category, severity, recommendation}]
    disqualification_clauses: list[dict[str, Any]] = field(default_factory=list)
    # P2：validator Agent 产出的交叉校验告警（[{type, message, agent_id}]）
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    """单个 Agent 的执行结果."""

    agent_id: str
    # 该 Agent 负责产出的字段（ParsedTender 的属性名 → 值）
    data: dict[str, Any]
    # Agent 级别 warnings（validator 产出的交叉校验告警在此）
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # 执行耗时（秒），用于可观测性
    elapsed_s: float = 0.0
    # 是否成功（False = 降级或失败）
    success: bool = True


def merge_agent_results(results: list[AgentResult]) -> ParsedTender:
    """将多 Agent 结果合并为 ParsedTender.

    合并规则：
    - 每个 Agent 负责自己的字段，直接赋值（不 concat 同一字段）；
    - warnings 全部汇总；
    - project_name / tender_no 取首个非空值（score_agent 产出）。

    P1 阶段：4 Agent 分别产出 score_points / disqualification_clauses /
    (format_requirements + glossary) / warnings，字段互不重叠。
    """
    merged = ParsedTender(
        score_points=[],
    )
    all_warnings: list[dict[str, Any]] = []

    for r in results:
        if not r.success:
            continue
        for key, val in r.data.items():
            if key == "score_points" and isinstance(val, list):
                merged.score_points = val
            elif key == "disqualification_clauses" and isinstance(val, list):
                merged.disqualification_clauses = val
            elif key == "format_requirements" and isinstance(val, list):
                merged.format_requirements = val
            elif key == "glossary" and isinstance(val, list):
                merged.glossary = val
            elif key == "project_name" and isinstance(val, str) and val and not merged.project_name:
                merged.project_name = val
            elif key == "tender_no" and isinstance(val, str) and val and not merged.tender_no:
                merged.tender_no = val
        all_warnings.extend(r.warnings)

    merged.warnings = all_warnings
    return merged
