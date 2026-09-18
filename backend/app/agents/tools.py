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
from app.services.infra import settings_service

logger = logging.getLogger(__name__)

# ───────────────────────── 工具 schema（OpenAI function 规范）─────────────────────────

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
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
    # ── Skill 契约体系三工具（S3）─────────────────────────────────────────
    # 对齐 OpenMAIC 的 create_skill / read / findSkill：Agent Runtime 按需消费行为准则。
    "create_skill": {
        "name": "create_skill",
        "description": (
            "把本次任务中总结出的可复用行为准则固化为一条新 skill。"
            "新建的 skill 默认处于**待审状态**（不立即生效），"
            "需人工在 Skill 设置页启用后才参与后续任务。"
            "若只是临时调整本次输出的写法，不要调用本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "skill 标识：小写字母开头，仅含小写字母/数字/下划线，3~64 字符",
                },
                "title": {"type": "string", "description": "展示名（简短中文名）"},
                "description": {
                    "type": "string",
                    "description": "适用场景描述（供人工审阅判断是否启用）",
                },
                "stage_key": {
                    "type": "string",
                    "description": "适用阶段",
                    "enum": [
                        "parse",
                        "score",
                        "outline",
                        "write",
                        "validate",
                        "consistency",
                        "review",
                        "export",
                    ],
                },
                "body_md": {
                    "type": "string",
                    "description": "行为准则正文（Markdown，≤8000 字符）",
                },
            },
            "required": ["name", "title", "description", "stage_key", "body_md"],
        },
    },
    "read_skill": {
        "name": "read_skill",
        "description": "读取某条 skill 的完整正文（行为准则）。用于确认当前实际生效的准则内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "skill 标识（如 parse_score / outline）"},
            },
            "required": ["name"],
        },
    },
    "find_skill": {
        "name": "find_skill",
        "description": (
            "按阶段或关键词检索可用的 skill 清单（返回 name/title/description/来源层，不含正文）。"
            "用于在开始某阶段任务前，先看清有哪些行为准则可用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage_key": {
                    "type": "string",
                    "description": "限定阶段（可选，缺省全部）",
                },
                "keyword": {
                    "type": "string",
                    "description": "关键词（可选，匹配 name/title/description）",
                },
            },
        },
    },
}

WRITE_TOOLS = ["kb_search", "get_score_points"]  # write_node 绑定
VALIDATE_TOOLS = ["list_sections", "get_score_points"]  # validate_node 绑定

# Skill 契约工具（默认**不**绑定到任何节点）—— 按需在节点内显式加入，
# 避免每次 LLM 调用都多背 3 个工具定义（token 成本）与多一轮工具循环延迟。
SKILL_TOOLS = ["create_skill", "read_skill", "find_skill"]


def get_tool_definitions(names: list[str]) -> list[dict[str, Any]]:
    """按名取工具的 OpenAI tools 封装（type=function）."""
    return [{"type": "function", "function": TOOL_SCHEMAS[name]} for name in names]


# ───────────────────────── 工具实现 ─────────────────────────


async def kb_search(
    project_id: str, query: str, doc_ids: list[str] | None = None
) -> list[dict[str, Any]]:
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
    from app.services.llm.rag_service import get_embedding, retrieve_with_rerank

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


async def get_score_points(project_id: str) -> list[dict[str, Any]]:
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


async def list_sections(project_id: str) -> list[dict[str, Any]]:
    """读取已生成章节（section_id/title/≤200 字摘要）."""
    from app.services.proposal.chapter_service import extract_chapter_summary

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


def update_glossary(
    glossary: list[dict[str, Any]], term: str, canonical: str, desc: str = ""
) -> list[dict[str, Any]]:
    """合并术语条目（同名覆盖），返回新列表（纯函数，不直写 DB/state）."""
    merged = [g for g in glossary if g.get("term") != term]
    return [*merged, {"term": term, "canonical": canonical, "desc": desc}]


# ───────────────────────── Skill 契约三工具（S3）─────────────────────────


async def create_skill(
    name: str,
    title: str,
    description: str,
    stage_key: str,
    body_md: str,
) -> dict[str, Any]:
    """把 Agent 总结的行为准则落成用户层 skill（**默认待审，不立即生效**）.

    产品口径①A：`created_by="llm"` ⇒ `enabled=False`，须人工在 Skill 设置页启用。
    失败（重名/内置同名/超长/非法阶段）返回 `{"ok": False, "error": ...}` 而**不抛异常**
    —— 工具循环里抛异常会中断整轮对话，而「建准则失败」不该拖垮主任务。
    """
    from app.services.skills import service as skill_service

    try:
        async with async_session_factory() as db:
            row = await skill_service.create_skill(
                db,
                name=name,
                title=title,
                description=description,
                stage_key=stage_key,
                body_md=body_md,
                created_by="llm",
            )
            await db.commit()
    except Exception as e:
        logger.warning("create_skill 失败: name=%s err=%s", name, e)
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "name": row.name,
        "enabled": row.enabled,
        "pendingReview": not row.enabled,
        "message": "准则已暂存为待审状态，需人工在 Skill 设置页启用后才生效",
    }


async def read_skill(name: str) -> dict[str, Any]:
    """读单条 skill 的契约详情（含正文）."""
    from app.services.skills import registry as skill_registry

    try:
        async with async_session_factory() as db:
            contract = await skill_registry.find_skill(name, db)
    except Exception as e:
        logger.warning("read_skill 失败: name=%s err=%s", name, e)
        return {"ok": False, "error": str(e)}
    if contract is None:
        return {"ok": False, "error": f"skill '{name}' 不存在"}
    return {
        "ok": True,
        "name": contract.name,
        "title": contract.title,
        "description": contract.description,
        "version": contract.version,
        "stageKey": contract.stage_key,
        "agentId": contract.agent_id,
        "source": "builtin" if contract.builtin else "user",
        "virtualPath": contract.virtual_path,
        "body": contract.body,
    }


async def find_skill(stage_key: str | None = None, keyword: str | None = None) -> dict[str, Any]:
    """检索可用 skill 清单（不含正文，只给 name/title/description/来源）."""
    from app.services.skills import registry as skill_registry

    try:
        async with async_session_factory() as db:
            contracts = await skill_registry.list_skills(db)
    except Exception as e:
        logger.warning("find_skill 失败: %s", e)
        return {"ok": False, "error": str(e)}

    items: list[dict[str, Any]] = []
    kw = (keyword or "").strip().lower()
    for c in contracts:
        if stage_key and c.stage_key != stage_key:
            continue
        if kw and kw not in f"{c.name} {c.title} {c.description}".lower():
            continue
        items.append(
            {
                "name": c.name,
                "title": c.title,
                "description": c.description,
                "stageKey": c.stage_key,
                "agentId": c.agent_id,
                "source": "builtin" if c.builtin else "user",
            }
        )
    return {"ok": True, "count": len(items), "skills": items}


async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    project_id: str,
    glossary: list[dict[str, Any]] | None = None,
) -> Any:
    """按名调度工具（chat_with_tools 的 executor 适配层）.

    外部工具：name 不在 TOOL_SCHEMAS 时视为外部工具 ID，走 registry.execute_external_tool。
    """
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
    # Skill 契约三工具（S3）
    if name == "create_skill":
        return await create_skill(
            arguments.get("name", ""),
            arguments.get("title", ""),
            arguments.get("description", ""),
            arguments.get("stage_key", ""),
            arguments.get("body_md", ""),
        )
    if name == "read_skill":
        return await read_skill(arguments.get("name", ""))
    if name == "find_skill":
        return await find_skill(arguments.get("stage_key"), arguments.get("keyword"))
    # 外部工具：name 为 tool_id（UUID 字符串），不在内置 TOOL_SCHEMAS 中
    if name not in TOOL_SCHEMAS:
        from app.services.infra.tools.registry import execute_external_tool as _ext_exec

        try:
            ext_tool_id = uuid.UUID(name)
        except (ValueError, AttributeError):
            raise ValueError(f"未知工具: {name}") from None
        return await _ext_exec(ext_tool_id, arguments.get("query", ""), project_id)
    raise ValueError(f"未知工具: {name}")


# ───────────────────────── 节点语义封装 ─────────────────────────


async def write_tool_preflight(
    project_id: str,
    chapter_title: str,
    base_context: str,
    doc_ids: list[Any] | None = None,
) -> str:
    """write 前置 Tool Calling（仅真实模式调用）：LLM 自主决定是否补充检索.

    绑定 kb_search/get_score_points + 该 stage 已绑定的外部搜索工具；
    kb_search 命中素材追加到 base_context 后返回（无调用/无命中时原样返回），
    原 retrieve 注入素材保持基础上下文。
    """
    from app.services.infra.tools.registry import get_definitions as get_ext_definitions
    from app.services.llm.llm_service import chat_with_tools

    async def executor(name: str, arguments: dict[str, Any]) -> str:
        result = await execute_tool(name, arguments, project_id)
        return json.dumps(result, ensure_ascii=False)

    # 合并内置工具 + 外部工具定义（外部工具真源 = stage_tool_bindings 显式绑定）
    builtin_tools = get_tool_definitions(WRITE_TOOLS)
    ext_tools = await get_ext_definitions("write", project_id)
    all_tools = builtin_tools + ext_tools

    _text, calls = await chat_with_tools(
        system_prompt=(
            f"你是投标技术方案撰写助手，正在撰写章节《{chapter_title}》。"
            "若判断已有素材不足以响应本章评分要求，可调用 kb_search 补充检索资料库素材；"
            "已有素材足够时直接回复「无需补充」，不要调用工具。"
        ),
        user_prompt=f"章节标题：{chapter_title}\n请判断是否需要补充检索。",
        tools=all_tools,
        executor=executor,
        stage_key="write",
        project_id=str(project_id),
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
    score_points: list[dict[str, Any]],
) -> list[str]:
    """validate 辅助取证复核（仅真实模式调用）：tool calling 复核 issues 是否真实成立.

    绑定 list_sections/get_score_points + 该 stage 已绑定的外部搜索工具取证；
    LLM 输出 {"keep": [...]}，仅保留仍成立的 issues；响应无法解析时保守保留全部。
    """
    from app.services.infra.tools.registry import get_definitions as get_ext_definitions
    from app.services.llm.llm_service import chat_with_tools

    async def executor(name: str, arguments: dict[str, Any]) -> str:
        result = await execute_tool(name, arguments, project_id)
        return json.dumps(result, ensure_ascii=False)

    # 合并内置工具 + 外部工具定义
    builtin_tools = get_tool_definitions(VALIDATE_TOOLS)
    ext_tools = await get_ext_definitions("validate", project_id)
    all_tools = builtin_tools + ext_tools

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
        tools=all_tools,
        executor=executor,
        stage_key="validate",
        project_id=str(project_id),
    )
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return issues
    keep = data.get("keep") if isinstance(data, dict) else None
    if not isinstance(keep, list):
        return issues
    return [i for i in issues if i in keep]
