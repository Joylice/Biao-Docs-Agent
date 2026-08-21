"""审阅阶段节点 — consistency_check / integrate / review(HITL) / rewrite / export + 路由."""

import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.core.config import settings
from app.models.document import Document
from app.models.proposal import ProposalSection
from app.services import benchmark_service, settings_service


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
            chapter_obj = next((c for c in outline if c["chapter_no"] == chapter_no), None)
            title = (chapter_obj or {}).get("title", "")
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
                async with _pkg.async_session_factory() as db:
                    await _pkg._persist_chapter_content(
                        db,
                        project_id,
                        chapter_no,
                        title,
                        new_content,
                        status="draft",
                        sections_tree=(chapter_obj or {}).get("sections", []),
                    )
                    await db.commit()  # BUG-2：重写章节显式提交
                await _pkg.publish_event(
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
                await _pkg.publish_event(
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
    await _pkg.publish_event(
        project_id,
        {
            "type": "warning",
            "message": f"全文一致性检查发现 {len(issues)} 个问题，未自动修复，请人工审阅",
            "issues": issues,
        },
    )
    return {"consistency_issues": issues}


async def integrate_node(state: dict) -> dict:
    """节点：全文整合 — 校验章节齐全 + E2 术语统一，进入审阅阶段."""
    from app.services.glossary_service import unify_terms

    project_id = state.get("project_id", "")
    outline = state.get("outline", [])
    chapters = dict(state.get("chapters", {}))
    missing = [c["chapter_no"] for c in outline if c["chapter_no"] not in chapters]
    if missing:
        return {"error": f"章节未生成完整，缺失: {missing}", "current_phase": "generate"}

    # 阶段 E2：术语表统一（mock 直通保证确定性输出；真实模式规则替换并落库）
    glossary = state.get("glossary") or []
    if glossary and not await settings_service.is_mock_enabled():
        for chapter_no in chapters:
            unified = unify_terms(chapters[chapter_no], glossary)
            if unified != chapters[chapter_no]:
                chapters[chapter_no] = unified
                chapter_obj = next((c for c in outline if c["chapter_no"] == chapter_no), None)
                async with _pkg.async_session_factory() as db:
                    await _pkg._persist_chapter_content(
                        db,
                        project_id,
                        chapter_no,
                        (chapter_obj or {}).get("title", ""),
                        unified,
                        status="draft",
                        sections_tree=(chapter_obj or {}).get("sections", []),
                    )
                    await db.commit()  # 术语统一后的章节显式提交

    async with _pkg.async_session_factory() as db:
        await _pkg._update_workflow(db, project_id, phase="review", progress=0.85, status="waiting")
        await db.commit()  # BUG-2：workflow 元数据写入显式提交
    await _pkg.publish_event(project_id, {"type": "progress", "phase": "review", "progress": 0.85})
    return {"current_phase": "review", "progress": 0.85, "chapters": chapters}


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
        chapter_obj = next((c for c in outline if c["chapter_no"] == chapter_no), None)
        title = (chapter_obj or {}).get("title", "")
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
            async with _pkg.async_session_factory() as db:
                await _pkg._persist_chapter_content(
                    db,
                    project_id,
                    chapter_no,
                    title,
                    new_content,
                    status="draft",
                    sections_tree=(chapter_obj or {}).get("sections", []),
                )
                db.add(_pkg._review_record(project_id, chapter_no, comment))
                await db.flush()
                await db.commit()  # BUG-2：章节重写 + 审阅记录显式提交
            await _pkg.publish_event(
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

    # 读取最新招标文件的格式要求驱动排版；失败不阻塞导出（回退默认样式）
    format_requirements = None
    try:
        async with _pkg.async_session_factory() as db:
            result = await db.execute(
                select(Document)
                .where(
                    Document.project_id == uuid.UUID(project_id),
                    Document.doc_type == "tender_file",
                )
                .order_by(Document.created_at.desc())
                .limit(1)
            )
            tender = result.scalar_one_or_none()
        if tender:
            format_requirements = (tender.meta or {}).get("format_requirements")
    except Exception:
        logger.exception("读取格式要求失败，使用默认排版")

    # 阶段 E4：引用溯源（E3 citations 按章聚合）+ 对标附表数据；失败降级不附加
    citations_by_chapter: dict[str, list[dict]] = {}
    benchmark_rows: list[dict] | None = None
    try:
        async with _pkg.async_session_factory() as db:
            sec_result = await db.execute(
                select(ProposalSection.section_id, ProposalSection.citations).where(
                    ProposalSection.project_id == uuid.UUID(project_id)
                )
            )
            for section_id, cits in sec_result.all():
                if isinstance(cits, list) and cits:
                    citations_by_chapter.setdefault(section_id.split(".")[0], []).extend(cits)
            benchmark_rows = await benchmark_service.build_benchmark(db, uuid.UUID(project_id))
    except Exception:
        logger.exception("引用/对标数据读取失败，导出降级不附加")

    try:
        storage_key = await export_to_word(
            chapters=chapters,
            outline=outline,
            project_name=project_name,
            format_requirements=format_requirements,
            company_name=settings.company_name,
            benchmark_rows=benchmark_rows or None,
            citations_by_chapter=citations_by_chapter or None,
        )
        async with _pkg.async_session_factory() as db:
            doc = Document(
                project_id=uuid.UUID(project_id),
                doc_type="export",
                title=f"{project_name}.docx",
                storage_key=storage_key,
                status="indexed",
                meta={"source": "workflow", "project_name": project_name},
            )
            db.add(doc)
            await _pkg._update_workflow(db, project_id, phase="done", progress=1.0, status="done")
            await db.commit()  # BUG-2：导出文档 + workflow 写入显式提交
        await _pkg.publish_event(
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
        async with _pkg.async_session_factory() as db:
            await _pkg._update_workflow(
                db, project_id, phase="export", status="failed", error=f"导出失败: {e}"
            )
            await db.commit()  # BUG-2：失败状态写入同样显式提交
        await _pkg.publish_event(project_id, {"type": "error", "message": f"导出失败: {e}"})
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
    """审阅路由：通过 → 导出；有反馈 → 重写；全部回派 → 重新等待审阅."""
    action = state.get("review_action")
    if action == "feedback":
        return "rewrite"
    if action == "redispatched":
        return "review"
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
