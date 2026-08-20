"""LangGraph Tool Calling 工具注册表（阶段 F，SDD §6.3 四工具落地）.

工具封装既有 service，经 ``llm_service.chat_with_tools`` 的 tool_call 循环调度：
- ``kb_search``：资料库检索（rag_service 召回+rerank），mock 确定性桩分支；
- ``get_score_points``：读当前项目评分点；
- ``list_sections``：读已生成章节摘要；
- ``update_glossary``：纯函数合并术语表（经节点返回写回 state.glossary）。

图拓扑不变：write_node 前置补充检索 / validate_node 辅助取证复核，
均仅真实模式触发，mock 模式与现版本行为等价。
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import ScorePoint
from app.models.proposal import ProposalSection
from app.services import settings_service

logger = logging.getLogger(__name__)

# ───────────────────────── 工具 schema（OpenAI function 规范）─────────────────────────

TOOL_SCHEMAS: dict[str, dict] = {
    "kb_search": {
        "name": "kb_search",
        "description": "检索公司资料库中与 query 相关的素材（embedding 召回 + rerank 精排）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词或问题"},
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定检索文档范围（可选，缺省全量）",
                },
            },
            "required": ["query"],
        },
    },
    "get_score_points": {
        "name": "get_score_points",
        "description": "读取当前项目的招标评分点清单（条款号/评分项/分值/判定标准）",
        "parameters": {"type": "object", "properties": {}},
    },
    "list_sections": {
        "name": "list_sections",
        "description": "读取当前项目已生成章节的标题与摘要（供取证与一致性比对）",
        "parameters": {"type": "object", "properties": {}},
    },
    "update_glossary": {
        "name": "update_glossary",
        "description": "更新术语表条目（同名术语覆盖，经节点返回合并 state.glossary）",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "术语原文"},
                "canonical": {"type": "string", "description": "规范表述"},
                "desc": {"type": "string", "description": "释义（可选）"},
            },
            "required": ["term", "canonical"],
        },
    },
}

WRITE_TOOLS = ["kb_search", "get_score_points"]  # write_node 绑定
VALIDATE_TOOLS = ["list_sections", "get_score_points"]  # validate_node 绑定


def get_tool_definitions(names: list[str]) -> list[dict]:
    """按名取工具的 OpenAI tools 封装（type=function）."""
    return [{"type": "function", "function": TOOL_SCHEMAS[name]} for name in names]


# ───────────────────────── 工具实现 ─────────────────────────


async def kb_search(project_id: str, query: str, doc_ids: list[str] | None = None) -> list[dict]:
    """资料库检索：mock 确定性桩 / 真实走 rag_service 召回+rerank."""
    if await settings_service.is_mock_enabled():
        # 确定性分支：E2E 可断言（内容含 query，结构稳定）
        return [
            {
                "doc_title": "mock 资料",
                "content": f"{query} 的 mock 检索素材",
                "page_no": 1,
                "score": 1.0,
            }
        ]
    from app.services.rag_service import get_embedding, retrieve_with_rerank

    query_embedding = await get_embedding(query)
    uuid_doc_ids = [uuid.UUID(d) for d in doc_ids] if doc_ids else None
    async with async_session_factory() as db:  # 只读块，无需 commit
        results = await retrieve_with_rerank(
            db=db,
            project_id=uuid.UUID(project_id),
            query=query,
            query_embedding=query_embedding,
            top_k=5,
            doc_ids=uuid_doc_ids,
        )
    return [
        {"doc_title": "", "content": r.content, "page_no": r.page_no, "score": float(r.score)}
        for r in results
    ]


async def get_score_points(project_id: str) -> list[dict]:
    """读取当前项目评分点（DB 为真源，两种模式均确定性）."""
    async with async_session_factory() as db:  # 只读块，无需 commit
        result = await db.execute(
            select(ScorePoint)
            .where(ScorePoint.project_id == uuid.UUID(project_id))
            .order_by(ScorePoint.clause_no)
        )
        return [
            {
                "clause_no": sp.clause_no,
                "item": sp.item,
                "score": float(sp.score) if sp.score is not None else None,
                "criteria": sp.criteria,
                "is_star": sp.is_star,
            }
            for sp in result.scalars().all()
        ]


async def list_sections(project_id: str) -> list[dict]:
    """读取已生成章节（section_id/title/≤200 字摘要）."""
    from app.services.chapter_service import extract_chapter_summary

    async with async_session_factory() as db:  # 只读块，无需 commit
        result = await db.execute(
            select(ProposalSection)
            .where(ProposalSection.project_id == uuid.UUID(project_id))
            .order_by(ProposalSection.section_id)
        )
        return [
            {
                "section_id": s.section_id,
                "title": s.title,
                "summary": extract_chapter_summary(s.content_md or ""),
            }
            for s in result.scalars().all()
        ]


def update_glossary(glossary: list[dict], term: str, canonical: str, desc: str = "") -> list[dict]:
    """合并术语条目（同名覆盖），返回新列表（纯函数，不直写 DB/state）."""
    merged = [g for g in glossary if g.get("term") != term]
    return [*merged, {"term": term, "canonical": canonical, "desc": desc}]


async def execute_tool(
    name: str, arguments: dict[str, Any], project_id: str, glossary: list[dict] | None = None
) -> Any:
    """按名调度工具（chat_with_tools 的 executor 适配层）."""
    if name == "kb_search":
        return await kb_search(project_id, arguments.get("query", ""), arguments.get("doc_ids"))
    if name == "get_score_points":
        return await get_score_points(project_id)
    if name == "list_sections":
        return await list_sections(project_id)
    if name == "update_glossary":
        return update_glossary(
            glossary or [],
            arguments.get("term", ""),
            arguments.get("canonical", ""),
            arguments.get("desc", ""),
        )
    raise ValueError(f"未知工具: {name}")


# ───────────────────────── 节点语义封装 ─────────────────────────


async def write_tool_preflight(
    project_id: str, chapter_title: str, base_context: str, doc_ids: list | None = None
) -> str:
    """write 前置 Tool Calling（仅真实模式调用）：LLM 自主决定是否补充检索.

    绑定 kb_search/get_score_points；kb_search 命中素材追加到 base_context
    后返回（无调用/无命中时原样返回），原 retrieve 注入素材保持基础上下文。
    """
    from app.services.llm_service import chat_with_tools

    async def executor(name: str, arguments: dict[str, Any]) -> str:
        result = await execute_tool(name, arguments, project_id)
        return json.dumps(result, ensure_ascii=False)

    _text, calls = await chat_with_tools(
        system_prompt=(
            f"你是投标技术方案撰写助手，正在撰写章节《{chapter_title}》。"
            "若判断已有素材不足以响应本章评分要求，可调用 kb_search 补充检索资料库素材；"
            "已有素材足够时直接回复「无需补充」，不要调用工具。"
        ),
        user_prompt=f"章节标题：{chapter_title}\n请判断是否需要补充检索。",
        tools=get_tool_definitions(WRITE_TOOLS),
        executor=executor,
    )
    extras: list[str] = []
    for call in calls:
        if call["name"] != "kb_search":
            continue
        try:
            hits = json.loads(call["result"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(hits, list):
            extras.extend(
                str(h.get("content", "")) for h in hits if isinstance(h, dict) and h.get("content")
            )
    if not extras:
        return base_context
    joined = "\n\n---\n\n".join(extras)
    return f"{base_context}\n\n---\n\n{joined}" if base_context else joined


async def validate_tool_recheck(
    project_id: str,
    chapter_no: str,
    content: str,
    issues: list[str],
    score_points: list[dict],
) -> list[str]:
    """validate 辅助取证复核（仅真实模式调用）：tool calling 复核 issues 是否真实成立.

    绑定 list_sections/get_score_points 取证；LLM 输出 {"keep": [...]}，
    仅保留仍成立的 issues；响应无法解析时保守保留全部（不放过真问题）。
    """
    from app.services.llm_service import chat_with_tools

    async def executor(name: str, arguments: dict[str, Any]) -> str:
        result = await execute_tool(name, arguments, project_id)
        return json.dumps(result, ensure_ascii=False)

    text, _calls = await chat_with_tools(
        system_prompt=(
            "你是投标方案校验复核员。给定章节校验发现的问题清单，请结合正文并可调用工具"
            "（list_sections/get_score_points）取证，判断每个问题是否真实成立。"
            '最终仅输出 JSON：{"keep": [仍成立的问题原文]}，不得输出其他内容。'
        ),
        user_prompt=(
            f"章节 {chapter_no} 正文：\n{content}\n\n"
            "待复核问题：\n" + "\n".join(f"- {i}" for i in issues)
        ),
        tools=get_tool_definitions(VALIDATE_TOOLS),
        executor=executor,
    )
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return issues
    keep = data.get("keep") if isinstance(data, dict) else None
    if not isinstance(keep, list):
        return issues
    return [i for i in issues if i in keep]
