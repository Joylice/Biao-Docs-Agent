"""LangGraph 节点函数 — 工作流各阶段实现（对齐 SDD §6）.

节点内通过 async_session_factory 打开 DB session（LangGraph 无 DI 注入）。
HITL 中断点：confirm_score_points / confirm_outline / review。

事务约定（BUG-2 修复）：``async with async_session_factory() as db`` 退出
仅 close 不 commit，写块必须在退出前显式 ``await db.commit()``，否则
proposal_skeletons / proposal_sections / reviews 等写入全部静默回滚。
只读块无需 commit（约定见 core.database.get_db docstring）。
"""

import logging
import time
import uuid

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import ScorePoint, TechRequirement
from app.models.project import Project
from app.models.proposal import ProposalSection, ProposalSkeleton, ProposalWorkflow
from app.services.event_service import publish_event

logger = logging.getLogger(__name__)

MIN_CHAPTER_LENGTH = 200  # 章节字数下限（validate 节点）
MAX_VALIDATE_RETRIES = 2  # 校验失败最大重试次数

# 三期 S4：section_token 节流参数（取先到者），避免 Redis 高频发布
STREAM_FLUSH_CHARS = 40  # 累积字符数上限
STREAM_FLUSH_SECS = 0.2  # 距上次发布间隔上限（秒）


# ───────────────────────── 内部工具 ─────────────────────────


async def _update_workflow(
    db,
    project_id: str,
    *,
    phase: str | None = None,
    progress: float | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """创建或更新项目工作流元数据."""
    result = await db.execute(
        select(ProposalWorkflow).where(ProposalWorkflow.project_id == uuid.UUID(project_id))
    )
    wf = result.scalar_one_or_none()
    if not wf:
        wf = ProposalWorkflow(project_id=uuid.UUID(project_id), thread_id=str(project_id))
        db.add(wf)
    if phase is not None:
        wf.phase = phase
    if progress is not None:
        wf.progress = progress
    if status is not None:
        wf.status = status
    if error is not None:
        wf.error = error
    await db.flush()


async def _load_tender_context(db, project_id: str) -> tuple[str, str, list[dict], list[dict]]:
    """读取项目名称/编号 + 已解析的评分点与技术需求."""
    proj_result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = proj_result.scalar_one_or_none()
    project_name = project.name if project else ""
    tender_no = project.tender_no or "" if project else ""

    sp_result = await db.execute(
        select(ScorePoint)
        .where(ScorePoint.project_id == uuid.UUID(project_id))
        .order_by(ScorePoint.clause_no)
    )
    score_points = [
        {
            "id": str(sp.id),
            "clause_no": sp.clause_no,
            "item": sp.item,
            "score": float(sp.score) if sp.score is not None else None,
            "criteria": sp.criteria,
            "is_star": sp.is_star,
            "strategy": sp.strategy,
            "risk_level": sp.risk_level,
            "confirmed": sp.confirmed,
        }
        for sp in sp_result.scalars().all()
    ]

    tr_result = await db.execute(
        select(TechRequirement)
        .where(TechRequirement.project_id == uuid.UUID(project_id))
        .order_by(TechRequirement.seq)
    )
    tech_requirements = [
        {
            "seq": tr.seq,
            "description": tr.description,
            "category": tr.category,
            "is_mandatory": tr.is_mandatory,
        }
        for tr in tr_result.scalars().all()
    ]
    return project_name, tender_no, score_points, tech_requirements


async def _upsert_skeleton(db, project_id: str, tree: list[dict]) -> None:
    """保存大纲到 proposal_skeletons（upsert）."""
    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == uuid.UUID(project_id))
    )
    skeleton = result.scalar_one_or_none()
    if not skeleton:
        skeleton = ProposalSkeleton(project_id=uuid.UUID(project_id), tree=tree)
        db.add(skeleton)
    else:
        skeleton.tree = tree
    await db.flush()


async def _upsert_section(
    db,
    project_id: str,
    section_id: str,
    title: str,
    content_md: str,
    status: str = "draft",
) -> None:
    """保存章节到 proposal_sections（upsert）."""
    result = await db.execute(
        select(ProposalSection).where(
            ProposalSection.project_id == uuid.UUID(project_id),
            ProposalSection.section_id == section_id,
        )
    )
    section = result.scalar_one_or_none()
    if not section:
        section = ProposalSection(
            project_id=uuid.UUID(project_id),
            section_id=section_id,
            title=title,
            content_md=content_md,
            status=status,
        )
        db.add(section)
    else:
        section.title = title
        section.content_md = content_md
        section.status = status
    await db.flush()


# ───────────────────────── 节点实现 ─────────────────────────


async def parse_tender_node(state: dict) -> dict:
    """节点：招标解析 — 从 DB 读取已确认解析结果（不重复调 LLM）."""
    project_id = state.get("project_id", "")
    if not project_id:
        return {"error": "缺少 project_id", "current_phase": "init"}

    try:
        async with async_session_factory() as db:
            project_name, tender_no, score_points, tech_requirements = await _load_tender_context(
                db, project_id
            )
            if not score_points:
                return {
                    "error": "项目尚未完成招标解析（无评分点），请先解析招标文件",
                    "current_phase": "init",
                }
            await _update_workflow(db, project_id, phase="confirm", progress=0.15, status="waiting")
            await db.commit()  # BUG-2：workflow 元数据写入显式提交
        return {
            "score_points": score_points,
            "tech_requirements": tech_requirements,
            "project_name": project_name,
            "tender_no": tender_no,
            "current_phase": "confirm",
            "progress": 0.15,
        }
    except Exception as e:
        logger.exception("读取解析结果失败")
        return {"error": f"读取解析结果失败: {e}", "current_phase": "init"}


async def confirm_score_points_node(state: dict) -> dict:
    """节点：HITL — 等待人工确认评分点."""
    from langgraph.types import interrupt

    decision = interrupt(
        {
            "type": "confirm_score_points",
            "score_points": state.get("score_points", []),
            "message": "请确认评分点提取结果",
        }
    )
    confirmed = decision is True or (
        isinstance(decision, dict) and decision.get("confirmed") is True
    )
    if not confirmed:
        return {"error": "评分点未确认", "current_phase": "confirm"}
    return {"current_phase": "outline", "progress": 0.25}


async def generate_outline_node(state: dict) -> dict:
    """节点：生成大纲 — 基于评分点和技术需求，落库 proposal_skeletons."""
    from app.services.llm_service import call_llm_with_schema
    from app.services.prompt_loader import load_outline_prompt

    project_id = state.get("project_id", "")
    score_points = state.get("score_points", [])
    tech_requirements = state.get("tech_requirements", [])

    system_prompt, user_prompt = load_outline_prompt(
        score_points=score_points,
        tech_requirements=tech_requirements,
    )

    try:
        result = await call_llm_with_schema(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "outline",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "chapters": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "chapter_no": {"type": "string"},
                                        "title": {"type": "string"},
                                        "sections": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "covered_clauses": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "本章节覆盖的评分点条款号",
                                        },
                                    },
                                    "required": ["chapter_no", "title", "covered_clauses"],
                                },
                            }
                        },
                        "required": ["chapters"],
                    },
                },
            },
        )
        outline = result.get("chapters", [])
        if not outline:
            return {
                "error": "大纲生成为空",
                "current_phase": "confirm",
                "regenerate_requested": False,
            }

        async with async_session_factory() as db:
            await _upsert_skeleton(db, project_id, outline)
            await _update_workflow(db, project_id, phase="outline", progress=0.35, status="waiting")
            await db.commit()  # BUG-2：skeleton + workflow 写入显式提交
        await publish_event(project_id, {"type": "progress", "phase": "outline", "progress": 0.35})
        return {"outline": outline, "current_phase": "outline", "progress": 0.35}
    except Exception as e:
        logger.exception("大纲生成失败")
        return {
            "error": f"大纲生成失败: {e}",
            "current_phase": "confirm",
            "regenerate_requested": False,
        }


async def confirm_outline_node(state: dict) -> dict:
    """节点：HITL — 等待人工确认大纲（支持二次编辑与 action=regenerate 重新生成）.

    resume 值：
    - True / {"confirmed": True} → 确认大纲，进入章节生成
    - {"confirmed": True, "outline": [...]} → 采用前端二次编辑后的大纲
      （替换 state.outline 并落库 proposal_skeletons），随后进入章节生成
    - {"confirmed": True, "mounted_doc_ids": [...]} → 资料库挂载配置写入 state
      （None=项目全量 / []=不挂载 / 列表=指定文档）
    - {"action": "regenerate"} → 用最新提示词重新生成大纲（复用 generate_outline_node
      逻辑，落库 proposal_skeletons 并更新 state.outline），随后再次 interrupt 挂起
      等待确认；循环支持多次重新生成。
    """
    from langgraph.types import interrupt

    while True:
        decision = interrupt(
            {
                "type": "confirm_outline",
                "outline": state.get("outline", []),
                "message": "请确认方案大纲",
            }
        )
        if isinstance(decision, dict):
            # 重新生成大纲：return 标记后经图边回 generate_outline 节点（节点返回值
            # 写入 checkpoint，保证 state 与 DB 落库一致），生成后回本节点再次挂起；
            # 不再内联调用 generate_outline_node（普通函数返回不经图，曾致 state 陈旧）
            if decision.get("action") == "regenerate":
                return {"regenerate_requested": True, "current_phase": "outline"}
            # 前端二次编辑后的大纲：替换 state.outline 并落库（DB 与 state 一致）
            if "outline" in decision and decision["outline"] is not None:
                state = {**state, "outline": decision["outline"]}
                async with async_session_factory() as db:
                    await _upsert_skeleton(db, state.get("project_id", ""), decision["outline"])
                    await db.commit()
            # 资料库挂载配置（None = 项目全量，[] = 不挂载）
            if "mounted_doc_ids" in decision:
                state = {**state, "mounted_doc_ids": decision["mounted_doc_ids"]}
        confirmed = decision is True or (
            isinstance(decision, dict) and decision.get("confirmed") is True
        )
        if not confirmed:
            return {
                "error": "大纲未确认",
                "current_phase": "outline",
                "regenerate_requested": False,
            }
        # 确认成功：清除二次编辑草稿（独立 DB 写；防陈旧草稿下次误恢复）
        async with async_session_factory() as db:
            await _clear_outline_draft(db, state.get("project_id", ""))
            await db.commit()
        updates: dict = {
            "current_phase": "generate",
            "progress": 0.4,
            "validate_retries": 0,
            "outline": state.get("outline", []),
            "regenerate_requested": False,
        }
        # 挂载配置仅在显式提交过时写入 state（缺省 None 保持项目全量检索）
        if "mounted_doc_ids" in state:
            updates["mounted_doc_ids"] = state["mounted_doc_ids"]
        return updates


async def _clear_outline_draft(db, project_id: str) -> None:
    """确认大纲后清除二次编辑草稿（幂等）."""
    result = await db.execute(
        select(ProposalSkeleton).where(ProposalSkeleton.project_id == uuid.UUID(project_id))
    )
    skeleton = result.scalar_one_or_none()
    if skeleton:
        skeleton.draft = None
        skeleton.draft_updated_at = None


async def retrieve_node(state: dict) -> dict:
    """节点：RAG 检索当前章节素材（召回+rerank 精排；检索失败降级为空素材）."""
    from app.services.chapter_service import flatten_sections
    from app.services.rag_service import get_embedding, retrieve_with_rerank

    project_id = state.get("project_id", "")
    outline = state.get("outline", [])
    chapters = state.get("chapters", {})
    # 资料库挂载配置（confirm-outline 写入）：None = 项目全量，[] = 不挂载
    mounted_doc_ids = state.get("mounted_doc_ids")

    # 找到下一个未生成的章节
    next_chapter = next((c for c in outline if c["chapter_no"] not in chapters), None)
    if not next_chapter:
        return {"current_chapter": "", "retrieved_context": ""}

    context = ""
    try:
        sec_text = " ".join(flatten_sections(next_chapter.get("sections", [])))
        query = f"{next_chapter.get('title', '')} {sec_text}"
        query_embedding = await get_embedding(query)
        async with async_session_factory() as db:  # 只读块，无需 commit
            results = await retrieve_with_rerank(
                db=db,
                project_id=uuid.UUID(project_id),
                query=query,
                query_embedding=query_embedding,
                top_k=8,
                doc_ids=(
                    [uuid.UUID(str(d)) for d in mounted_doc_ids]
                    if mounted_doc_ids is not None
                    else None
                ),
            )
        context = "\n\n---\n\n".join(r.content for r in results)
    except Exception as e:
        logger.warning("RAG 检索失败（降级无素材）: %s", e)

    return {"current_chapter": next_chapter["chapter_no"], "retrieved_context": context}


async def write_node(state: dict) -> dict:
    """节点：撰写章节 — RAG 素材 + LLM 生成，落库 proposal_sections 并推送事件.

    章节间上下文：按大纲顺序汇总已完成章节摘要（state.chapter_summaries）
    注入提示词防重复保衔接；生成后提取本章 ≤200 字摘要回存。
    """
    from app.services.chapter_service import extract_chapter_summary, generate_chapter
    from app.services.coverage_service import compute_coverage

    project_id = state.get("project_id", "")
    chapter_no = state.get("current_chapter", "")
    outline = state.get("outline", [])
    chapters = dict(state.get("chapters", {}))
    summaries = dict(state.get("chapter_summaries", {}))
    # 资料库挂载配置（confirm-outline 写入）：None = 项目全量，[] = 不挂载
    mounted_doc_ids = state.get("mounted_doc_ids")

    chapter = next((c for c in outline if c["chapter_no"] == chapter_no), None)
    if not chapter:
        return {"error": f"章节 {chapter_no} 不在大纲中", "current_phase": "generate"}

    # 已完成章节摘要（按大纲顺序，仅取已生成章节）
    prior_summaries = [
        {
            "chapter_no": c["chapter_no"],
            "title": summaries[c["chapter_no"]].get("title", c.get("title", "")),
            "summary": summaries[c["chapter_no"]].get("summary", ""),
        }
        for c in outline
        if c["chapter_no"] in summaries and c["chapter_no"] != chapter_no
    ]

    # 评分点覆盖矩阵：未覆盖的 confirmed 评分点注入本章提示词补写，覆盖率随 progress 推送
    coverage = compute_coverage(state.get("score_points", []), outline)

    # 三期 S4：真流式 — on_delta 节流发布 section_token（≥ STREAM_FLUSH_CHARS 字符
    # 或距上次 ≥ STREAM_FLUSH_SECS 秒，取先到者）；结束后尾部缓冲区兜底 flush
    token_buffer: list[str] = []
    token_buf_len = 0
    last_token_at = time.monotonic()

    async def _flush_tokens() -> None:
        nonlocal token_buf_len, last_token_at
        if not token_buffer:
            return
        await publish_event(
            project_id,
            {"type": "section_token", "chapter_no": chapter_no, "delta": "".join(token_buffer)},
        )
        token_buffer.clear()
        token_buf_len = 0
        last_token_at = time.monotonic()

    async def on_delta(delta: str) -> None:
        nonlocal token_buf_len
        token_buffer.append(delta)
        token_buf_len += len(delta)
        overdue = time.monotonic() - last_token_at >= STREAM_FLUSH_SECS
        if token_buf_len >= STREAM_FLUSH_CHARS or overdue:
            await _flush_tokens()

    try:
        async with async_session_factory() as db:  # 只读块（RAG 兜底检索），无需 commit
            content = await generate_chapter(
                chapter=chapter,
                score_points=state.get("score_points", []),
                tech_requirements=state.get("tech_requirements", []),
                project_id=uuid.UUID(project_id),
                context=state.get("retrieved_context", ""),
                db=db,
                doc_ids=(
                    [uuid.UUID(str(d)) for d in mounted_doc_ids]
                    if mounted_doc_ids is not None
                    else None
                ),
                on_delta=on_delta,
                prior_summaries=prior_summaries,
                supplement_points=coverage["uncovered"],
            )
    except Exception as e:
        logger.exception("章节生成失败")
        return {"error": f"章节 {chapter_no} 生成失败: {e}", "current_phase": "generate"}

    await _flush_tokens()  # 尾部未达阈值的缓冲也要发出，保证 delta 拼接 == 全文

    async with async_session_factory() as db:
        await _upsert_section(
            db, project_id, chapter_no, chapter.get("title", ""), content, status="draft"
        )
        total = len(outline)
        progress = round(0.4 + 0.35 * (len(chapters) + 1) / max(total, 1), 2)
        await _update_workflow(
            db, project_id, phase="generate", progress=progress, status="running"
        )
        await db.commit()  # BUG-2：章节 + workflow 写入显式提交

    chapters[chapter_no] = content
    summaries[chapter_no] = {
        "title": chapter.get("title", ""),
        "summary": extract_chapter_summary(content),
    }
    await publish_event(
        project_id,
        {
            "type": "section_done",
            "chapter_no": chapter_no,
            "title": chapter.get("title", ""),
            "content": content,
        },
    )
    await publish_event(
        project_id,
        {
            "type": "progress",
            "phase": "generate",
            "progress": progress,
            "current_chapter": chapter_no,
            "coverage_rate": coverage["coverage_rate"],
        },
    )
    return {
        "chapters": chapters,
        "chapter_summaries": summaries,
        "current_phase": "generate",
        "progress": progress,
    }


def validate_node(state: dict) -> dict:
    """节点：校验章节 — 字数下限 + 评分点关键词覆盖（失败可重试 ≤2 次）."""
    chapter_no = state.get("current_chapter", "")
    content = state.get("chapters", {}).get(chapter_no, "")
    retries = state.get("validate_retries", 0)

    issues: list[str] = []
    if len(content.strip()) < MIN_CHAPTER_LENGTH:
        issues.append(f"字数不足（{len(content.strip())} < {MIN_CHAPTER_LENGTH}）")

    # 评分点关键词覆盖检查（仅检查 ★ 评分点标题）
    score_points = state.get("score_points", [])
    for sp in score_points:
        if sp.get("is_star") and sp.get("item") and sp["item"][:4] not in content:
            issues.append(f"未覆盖评分点 {sp.get('clause_no', '')}：{sp['item'][:20]}")

    if issues and retries < MAX_VALIDATE_RETRIES:
        return {"validation_ok": False, "validate_retries": retries + 1}
    return {"validation_ok": True, "validate_retries": retries}


async def consistency_check_node(state: dict) -> dict:
    """节点：全文一致性检查（integrate 前）— 术语冲突/重复段落/编号断裂.

    一次 LLM 调用产出 issues；可修复且未重写过 → 按章节聚合意见走一轮
    定向重写（复用 rewrite 链路，最多 1 次）；否则发 warning 事件不阻塞导出。
    检查异常降级无问题继续（一致性检查不阻塞交付主链路）。
    """
    from app.services.chapter_service import extract_chapter_summary
    from app.services.consistency_service import check_consistency
    from app.services.review_service import rewrite_chapter

    project_id = state.get("project_id", "")
    chapters = dict(state.get("chapters", {}))
    summaries = dict(state.get("chapter_summaries", {}))
    outline = state.get("outline", [])

    try:
        issues = await check_consistency(chapters, outline)
    except Exception as e:
        logger.warning("全文一致性检查失败（降级继续）: %s", e)
        issues = []

    if not issues:
        return {"consistency_issues": []}

    fixable = [i for i in issues if i.get("fixable") and i.get("chapter_no") in chapters]
    if fixable and not state.get("consistency_retried"):
        # 同章多 issue 聚合为一条重写意见，一轮定向重写
        comments: dict[str, list[str]] = {}
        for issue in fixable:
            comments.setdefault(issue["chapter_no"], []).append(issue.get("description", ""))
        for chapter_no, descs in comments.items():
            title = next((c.get("title", "") for c in outline if c["chapter_no"] == chapter_no), "")
            try:
                new_content = await rewrite_chapter(
                    chapter_no=chapter_no,
                    original_content=chapters[chapter_no],
                    comment="全文一致性问题修复：\n" + "\n".join(f"- {d}" for d in descs),
                )
                chapters[chapter_no] = new_content
                if chapter_no in summaries:
                    summaries[chapter_no] = {
                        **summaries[chapter_no],
                        "summary": extract_chapter_summary(new_content),
                    }
                async with async_session_factory() as db:
                    await _upsert_section(
                        db, project_id, chapter_no, title, new_content, status="draft"
                    )
                    await db.commit()  # BUG-2：重写章节显式提交
                await publish_event(
                    project_id,
                    {
                        "type": "section_done",
                        "chapter_no": chapter_no,
                        "title": title,
                        "content": new_content,
                    },
                )
            except Exception as e:
                logger.warning("一致性修复重写失败（降级告警）: %s", e)
                await publish_event(
                    project_id,
                    {
                        "type": "warning",
                        "message": f"章节 {chapter_no} 一致性修复失败，请人工审阅",
                        "issues": issues,
                    },
                )
        return {
            "chapters": chapters,
            "chapter_summaries": summaries,
            "consistency_issues": issues,
            "consistency_retried": True,
        }

    # 不可修复 / 已重写过一轮 → 告警事件不阻塞导出
    await publish_event(
        project_id,
        {
            "type": "warning",
            "message": f"全文一致性检查发现 {len(issues)} 个问题，未自动修复，请人工审阅",
            "issues": issues,
        },
    )
    return {"consistency_issues": issues}


async def integrate_node(state: dict) -> dict:
    """节点：全文整合 — 校验章节齐全，进入审阅阶段."""
    project_id = state.get("project_id", "")
    outline = state.get("outline", [])
    chapters = state.get("chapters", {})
    missing = [c["chapter_no"] for c in outline if c["chapter_no"] not in chapters]
    if missing:
        return {"error": f"章节未生成完整，缺失: {missing}", "current_phase": "generate"}

    async with async_session_factory() as db:
        await _update_workflow(db, project_id, phase="review", progress=0.85, status="waiting")
        await db.commit()  # BUG-2：workflow 元数据写入显式提交
    await publish_event(project_id, {"type": "progress", "phase": "review", "progress": 0.85})
    return {"current_phase": "review", "progress": 0.85}


async def review_node(state: dict) -> dict:
    """节点：HITL 审阅 — interrupt 等待人工通过/反馈."""
    from langgraph.types import interrupt

    decision = interrupt(
        {
            "type": "review_request",
            "chapters": state.get("chapters", {}),
            "score_points": state.get("score_points", []),
            "message": "请审阅章节内容（approved / feedback）",
        }
    )
    if isinstance(decision, dict):
        action = decision.get("action", "approved")
        feedback = decision.get("feedback", {})
    else:
        action = "approved"
        feedback = {}
    return {"review_action": action, "review_feedback": feedback}


async def rewrite_node(state: dict) -> dict:
    """节点：按反馈局部重写 — 记录 reviews 表并重写指定章节（同步刷新摘要）."""
    from app.services.chapter_service import extract_chapter_summary
    from app.services.review_service import rewrite_chapter

    project_id = state.get("project_id", "")
    feedback = state.get("review_feedback", {})
    chapters = dict(state.get("chapters", {}))
    summaries = dict(state.get("chapter_summaries", {}))
    outline = state.get("outline", [])
    if not feedback:
        return {"error": "无审阅反馈可重写", "current_phase": "review"}

    for chapter_no, comment in feedback.items():
        if chapter_no not in chapters:
            continue
        title = next((c.get("title", "") for c in outline if c["chapter_no"] == chapter_no), "")
        try:
            new_content = await rewrite_chapter(
                chapter_no=chapter_no,
                original_content=chapters[chapter_no],
                comment=comment,
            )
            chapters[chapter_no] = new_content
            if chapter_no in summaries:  # 重写后刷新摘要，保持章间上下文同步
                summaries[chapter_no] = {
                    **summaries[chapter_no],
                    "summary": extract_chapter_summary(new_content),
                }
            async with async_session_factory() as db:
                await _upsert_section(
                    db, project_id, chapter_no, title, new_content, status="draft"
                )
                db.add(_review_record(project_id, chapter_no, comment))
                await db.flush()
                await db.commit()  # BUG-2：章节重写 + 审阅记录显式提交
            await publish_event(
                project_id,
                {
                    "type": "section_done",
                    "chapter_no": chapter_no,
                    "title": title,
                    "content": new_content,
                },
            )
        except Exception as e:
            logger.exception("章节重写失败")
            return {"error": f"章节 {chapter_no} 重写失败: {e}", "current_phase": "review"}

    return {
        "chapters": chapters,
        "chapter_summaries": summaries,
        "current_phase": "review",
        "progress": 0.85,
    }


def _review_record(project_id: str, chapter_no: str, comment: str):
    """构造审阅记录（延迟 import 避免循环依赖）."""
    from app.models.proposal import Review

    return Review(
        project_id=uuid.UUID(project_id),
        section_id=chapter_no,
        action="rewrite",
        content=comment,
    )


async def export_node(state: dict) -> dict:
    """节点：导出 Word — 写入 documents(doc_type=export) 并推送完成事件."""
    from app.services.export_service import export_to_word

    project_id = state.get("project_id", "")
    chapters = state.get("chapters", {})
    outline = state.get("outline", [])
    project_name = state.get("project_name", "技术方案")

    try:
        storage_key = await export_to_word(
            chapters=chapters,
            outline=outline,
            project_name=project_name,
        )
        async with async_session_factory() as db:
            from app.models.document import Document

            doc = Document(
                project_id=uuid.UUID(project_id),
                doc_type="export",
                title=f"{project_name}.docx",
                storage_key=storage_key,
                status="indexed",
                meta={"source": "workflow", "project_name": project_name},
            )
            db.add(doc)
            await _update_workflow(db, project_id, phase="done", progress=1.0, status="done")
            await db.commit()  # BUG-2：导出文档 + workflow 写入显式提交
        await publish_event(
            project_id,
            {"type": "task_done", "export_storage_key": storage_key},
        )
        return {
            "export_storage_key": storage_key,
            "export_status": "done",
            "current_phase": "done",
            "progress": 1.0,
        }
    except Exception as e:
        logger.exception("导出失败")
        async with async_session_factory() as db:
            await _update_workflow(
                db, project_id, phase="export", status="failed", error=f"导出失败: {e}"
            )
            await db.commit()  # BUG-2：失败状态写入同样显式提交
        await publish_event(project_id, {"type": "error", "message": f"导出失败: {e}"})
        return {"error": f"导出失败: {e}", "export_status": "failed"}


# ───────────────────────── 条件路由 ─────────────────────────


def chapter_route(state: dict) -> str:
    """章节循环路由：校验失败重试 / 还有章节继续 / 全部完成整合."""
    if state.get("error"):
        return "integrate"
    if not state.get("validation_ok", True):
        return "write"
    outline = state.get("outline", [])
    chapters = state.get("chapters", {})
    remaining = [c for c in outline if c["chapter_no"] not in chapters]
    if remaining:
        return "retrieve"
    return "consistency_check"


def review_route(state: dict) -> str:
    """审阅路由：通过 → 导出；有反馈 → 重写."""
    if state.get("review_action") == "feedback":
        return "rewrite"
    return "export"


# ── 兼容旧测试的路由函数（图内已改用 chapter_route/review_route）──


def route_after_confirm(state: dict) -> str:
    """人工确认后路由."""
    if state.get("score_points_confirmed"):
        return "generate_outline"
    return "confirm"  # 回到确认（interrupt）


def route_after_outline_confirmed(state: dict) -> str:
    """大纲确认后路由到章节生成."""
    if state.get("outline_confirmed"):
        return "generate_chapter"
    return "confirm_outline"  # 回到确认
