"""章节生成循环节点 — retrieve（RAG 检索）/ write（LLM 撰写）/ validate（校验）."""

import time
import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.services.infra import benchmark_service, kb_base_service, settings_service


async def retrieve_node(state: dict) -> dict:
    """节点：RAG 检索当前章节素材（召回+rerank 精排；检索失败降级为空素材）."""
    from app.services.llm.rag_service import get_embedding, retrieve_with_rerank
    from app.services.proposal.chapter_service import flatten_sections

    project_id = state.get("project_id", "")
    outline = state.get("outline", [])
    chapters = state.get("chapters", {})
    # 资料库挂载配置（confirm-outline 写入）：None = 项目全量，[] = 不挂载
    mounted_doc_ids = state.get("mounted_doc_ids")
    mounted_kb_ids = state.get("mounted_kb_ids")

    # 找到下一个未生成的章节
    next_chapter = next((c for c in outline if c["chapter_no"] not in chapters), None)
    if not next_chapter:
        return {"current_chapter": "", "retrieved_context": "", "retrieved_citations": []}

    context = ""
    citations: list[dict] = []
    try:
        sec_text = " ".join(flatten_sections(next_chapter.get("sections", [])))
        query = f"{next_chapter.get('title', '')} {sec_text}"
        query_embedding = await get_embedding(query)
        async with _pkg.async_session_factory() as db:  # 只读块，无需 commit
            doc_ids = await kb_base_service.resolve_mount_doc_ids(
                db, mounted_kb_ids, mounted_doc_ids
            )
            results = await retrieve_with_rerank(
                db=db,
                project_id=uuid.UUID(project_id),
                query=query,
                query_embedding=query_embedding,
                top_k=8,
                doc_ids=doc_ids,
            )
        context = "\n\n---\n\n".join(r.content for r in results)
        # 阶段 E3 引用溯源：命中 chunk 元数据按 chunk_id 去重，补齐文档标题后随章节落库
        if results:
            from app.models.document import Document

            doc_id_set = list({r.doc_id for r in results})
            title_result = await db.execute(
                select(Document.id, Document.title).where(Document.id.in_(doc_id_set))
            )
            titles = {row[0]: row[1] for row in title_result.all()}
            seen: set = set()
            for r in results:
                if r.chunk_id in seen:
                    continue
                seen.add(r.chunk_id)
                citations.append(
                    {
                        "chunk_id": str(r.chunk_id),
                        "doc_title": titles.get(r.doc_id, ""),
                        "page_no": r.page_no,
                    }
                )
    except Exception as e:
        logger.warning("RAG 检索失败（降级无素材）: %s", e)

    return {
        "current_chapter": next_chapter["chapter_no"],
        "retrieved_context": context,
        "retrieved_citations": citations,
    }


async def write_node(state: dict) -> dict:
    """节点：撰写章节 — RAG 素材 + LLM 生成，落库 proposal_sections 并推送事件.

    章节间上下文：按大纲顺序汇总已完成章节摘要（state.chapter_summaries）
    注入提示词防重复保衔接；生成后提取本章 ≤200 字摘要回存。
    """
    from app.services.proposal.chapter_service import extract_chapter_summary, generate_chapter
    from app.services.proposal.coverage_service import compute_coverage

    project_id = state.get("project_id", "")
    chapter_no = state.get("current_chapter", "")
    outline = state.get("outline", [])
    chapters = dict(state.get("chapters", {}))
    summaries = dict(state.get("chapter_summaries", {}))
    # 资料库挂载配置（confirm-outline 写入）：None = 项目全量，[] = 不挂载
    mounted_doc_ids = state.get("mounted_doc_ids")
    mounted_kb_ids = state.get("mounted_kb_ids")

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

    # 血缘校验（MVP 非阻塞）：大纲生成时的 context_version 与当前 state.context_version
    # 不一致时告警，提示用户大纲基于旧数据建议重新生成；ocv 为 None（正常路径/旧 checkpoint）时跳过
    ocv, cv = state.get("outline_context_version"), state.get("context_version")
    if ocv and cv and ocv != cv:
        await _pkg.publish_event(
            project_id,
            {
                "type": "warning",
                "message": "上下文已刷新，当前大纲基于旧数据，建议重新生成",
            },
        )

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
        await _pkg.publish_event(
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
        overdue = time.monotonic() - last_token_at >= _pkg.STREAM_FLUSH_SECS
        if token_buf_len >= _pkg.STREAM_FLUSH_CHARS or overdue:
            await _flush_tokens()

    try:
        async with _pkg.async_session_factory() as db:  # 只读块（RAG 兜底检索），无需 commit
            doc_ids = await kb_base_service.resolve_mount_doc_ids(
                db, mounted_kb_ids, mounted_doc_ids
            )
            # 阶段 D（1.4）：高风险评分点应对策略注入本章提示词
            high_risk = await benchmark_service.load_high_risk_points(db, uuid.UUID(project_id))
            # 阶段 F：Tool Calling 前置补充检索（仅真实模式；mock/异常降级保持原上下文）
            context = state.get("retrieved_context", "")
            if not await settings_service.is_mock_enabled():
                from app.agents.tools import write_tool_preflight

                try:
                    context = await write_tool_preflight(
                        project_id, chapter.get("title", ""), context, doc_ids
                    )
                except Exception as e:
                    logger.warning("write 工具前置检索失败（降级原上下文）: %s", e)
            content = await generate_chapter(
                chapter=chapter,
                score_points=state.get("score_points", []),
                tech_requirements=state.get("tech_requirements", []),
                project_id=uuid.UUID(project_id),
                context=context,
                db=db,
                doc_ids=doc_ids,
                on_delta=on_delta,
                prior_summaries=prior_summaries,
                supplement_points=coverage["uncovered"],
                benchmark_high_risk=high_risk,
                glossary=state.get("glossary", []),
            )
    except Exception as e:
        logger.exception("章节生成失败")
        return {"error": f"章节 {chapter_no} 生成失败: {e}", "current_phase": "generate"}

    await _flush_tokens()  # 尾部未达阈值的缓冲也要发出，保证 delta 拼接 == 全文

    async with _pkg.async_session_factory() as db:
        await _pkg._persist_chapter_content(
            db,
            project_id,
            chapter_no,
            chapter.get("title", ""),
            content,
            status="draft",
            sections_tree=chapter.get("sections", []),
            citations=state.get("retrieved_citations") or None,
        )
        total = len(outline)
        progress = round(0.4 + 0.35 * (len(chapters) + 1) / max(total, 1), 2)
        await _pkg._update_workflow(
            db, project_id, phase="generate", progress=progress, status="running"
        )
        await db.commit()  # BUG-2：章节 + workflow 写入显式提交

    chapters[chapter_no] = content
    summaries[chapter_no] = {
        "title": chapter.get("title", ""),
        "summary": extract_chapter_summary(content),
    }
    await _pkg.publish_event(
        project_id,
        {
            "type": "section_done",
            "chapter_no": chapter_no,
            "title": chapter.get("title", ""),
            "content": content,
        },
    )
    await _pkg.publish_event(
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


async def validate_node(state: dict) -> dict:
    """节点：校验章节 — 字数下限 + 评分点关键词覆盖 + E1 参数比对（失败可重试 ≤2 次）."""
    from app.services.proposal.param_check_service import check_chapter_params

    chapter_no = state.get("current_chapter", "")
    content = state.get("chapters", {}).get(chapter_no, "")
    retries = state.get("validate_retries", 0)

    issues: list[str] = []
    if len(content.strip()) < _pkg.MIN_CHAPTER_LENGTH:
        issues.append(f"字数不足（{len(content.strip())} < {_pkg.MIN_CHAPTER_LENGTH}）")

    # 评分点关键词覆盖检查（仅检查 ★ 评分点标题）
    score_points = state.get("score_points", [])
    for sp in score_points:
        if sp.get("is_star") and sp.get("item") and sp["item"][:4] not in content:
            issues.append(f"未覆盖评分点 {sp.get('clause_no', '')}：{sp['item'][:20]}")

    # 阶段 E1：★ 评分点参数断言 vs 正文（param_mismatch 走同一重试链路）
    issues.extend(await check_chapter_params(content, score_points))

    # 阶段 H：废标条款校验 — 正文触碰已确认 high 红线条款即追加风险项；
    # 比对异常降级放行（不阻塞主链路）
    disqualification_risk = False
    project_id = state.get("project_id", "")
    if project_id:
        from app.services.proposal.disqualification_service import check_chapter_content

        try:
            dq_hits = await check_chapter_content(project_id, content)
        except Exception as e:
            logger.warning("废标条款校验失败（降级继续）: %s", e)
            dq_hits = []
        for hit in dq_hits:
            disqualification_risk = True
            issues.append(f"废标风险 {hit.get('clause_no', '')}：{hit.get('title', '')}")

    # 阶段 F：真实模式下 tool calling 辅助取证复核（mock/异常保留原 issues）
    if issues and not await settings_service.is_mock_enabled():
        from app.agents.tools import validate_tool_recheck

        try:
            issues = await validate_tool_recheck(
                state.get("project_id", ""), chapter_no, content, issues, score_points
            )
        except Exception as e:
            logger.warning("校验问题工具复核失败（保留原 issues）: %s", e)

    if issues and retries < _pkg.MAX_VALIDATE_RETRIES:
        return {
            "validation_ok": False,
            "validate_retries": retries + 1,
            "disqualification_risk": disqualification_risk,
        }
    return {
        "validation_ok": True,
        "validate_retries": retries,
        "disqualification_risk": disqualification_risk,
    }
