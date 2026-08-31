"""章节生成服务 — RAG 增强 + LLM 生成."""

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import redact
from app.core.sorting import is_nested_sections, numbered_sections  # noqa: F401 — 向后兼容 re-export
from app.models.proposal import ProposalSection
from app.services.infra.prompt_loader import load_chapter_prompt
from app.services.llm.llm_service import call_llm_stream, call_llm_text

SUMMARY_MAX_LEN = 200  # 章节摘要上限（章节间上下文注入）

_SUMMARY_MARKER_RE = re.compile(r"^#{1,6}\s*|^[-*+]\s*|^\d+[.、]\s*")


def extract_chapter_summary(content: str, max_len: int = SUMMARY_MAX_LEN) -> str:
    """从章节正文提取 ≤max_len 字摘要（去 Markdown 标记、压缩空白、截断）."""
    lines: list[str] = []
    for line in content.splitlines():
        stripped = _SUMMARY_MARKER_RE.sub("", line.strip())
        if stripped:
            lines.append(stripped)
    text = " ".join(lines).strip()
    return text[:max_len]


def flatten_sections(sections: list) -> list[str]:
    """大纲子节拍平为标题列表（兼容 string[] 与二次编辑产物的嵌套树）.

    LLM 输出的 string[] 原样返回（不追加编号，保持既有章节提示词形态）；
    嵌套树 {title, children} 递归推导编号（1 / 1.1 / 1.1.1 …），供章节
    提示词与 RAG 检索使用。
    """
    if all(isinstance(s, str) for s in sections):
        return [s for s in sections if s]

    out: list[str] = []

    def _walk(nodes: list, prefix: str) -> None:
        for i, node in enumerate(nodes, 1):
            no = f"{prefix}{i}"
            if isinstance(node, str):
                if node.strip():
                    out.append(f"{no} {node.strip()}")
            elif isinstance(node, dict):
                title = str(node.get("title", "")).strip()
                if title:
                    out.append(f"{no} {title}")
                children = node.get("children") or []
                if children:
                    _walk(children, f"{no}.")
            # 其他类型忽略（防御脏数据）

    _walk(sections, "")
    return out


def _numbered_tree(nodes: list, prefix: str, out: list[tuple[str, str]]) -> None:
    """嵌套树递归推导编号标题对 [(no, title)]（与 flatten_sections 编号规则一致）.

    已迁移至 app.core.sorting，此处保留为向后兼容 re-export.
    """
    from app.core.sorting import _numbered_tree as _impl
    _impl(nodes, prefix, out)


_HEADING_RE = re.compile(r"^#{2,6}\s+(.*)$")
_LEADING_NO_RE = re.compile(r"^[\d.]+\s*")


def split_chapter_to_sections(content_md: str, sections_tree: list, chapter_no: str) -> list[dict]:
    """按大纲嵌套树将整章正文切分为子节片段.

    仅当 sections_tree 含 dict 节点（嵌套树）时切分，否则返回 []（调用方保持
    章级存储，向后兼容 string[] 大纲）。切分规则：按树序在正文中匹配 `##`~
    `######` 标题行（容忍标题前编号如 `1.1`）；首个命中标题之前的前置文本
    并入首个子节，未匹配标题的段落并入其前一子节（匹配失败不阻塞）。
    返回 [{section_id, title, content}]，section_id = {chapter_no}.{序号…}。
    """
    if not is_nested_sections(sections_tree):
        return []
    numbered = numbered_sections(sections_tree, chapter_no)
    if not numbered:
        return []

    def _norm(title: str) -> str:
        return _LEADING_NO_RE.sub("", title.strip()).strip()

    lines = content_md.splitlines()
    # 按树序依次为每个子节定位命中的标题行（单调向后扫描，容忍缺失）
    matched_line: list[int | None] = []
    pos = 0
    for _, title in numbered:
        target = _norm(title)
        hit: int | None = None
        if target:
            for li in range(pos, len(lines)):
                m = _HEADING_RE.match(lines[li].strip())
                if m and _norm(m.group(1)) == target:
                    hit = li
                    pos = li + 1
                    break
        matched_line.append(hit)

    # 有效锚点（命中的子节及其行号），保持树序
    anchors = [(idx, li) for idx, li in enumerate(matched_line) if li is not None]
    results: list[dict] = []
    if not anchors:
        # 全部未命中：整章并入首个子节（不阻塞）
        first_no, first_title = numbered[0]
        return [{"section_id": first_no, "title": first_title, "content": content_md.strip()}]

    for ai, (sec_idx, line_idx) in enumerate(anchors):
        end = anchors[ai + 1][1] if ai + 1 < len(anchors) else len(lines)
        seg = "\n".join(lines[line_idx:end]).strip()
        if ai == 0 and line_idx > 0:
            # 首标题之前的前置文本并入首个子节
            prefix_text = "\n".join(lines[:line_idx]).strip()
            if prefix_text:
                seg = f"{prefix_text}\n\n{seg}" if seg else prefix_text
        no, title = numbered[sec_idx]
        results.append({"section_id": no, "title": title, "content": seg})

    # 未命中的子节（无锚点）不产生空行；其应得内容已按「并入前一子节」规则归属
    return results


async def generate_chapter(
    chapter: dict,
    score_points: list[dict],
    tech_requirements: list[dict],
    project_id: uuid.UUID,
    context: str = "",
    db: AsyncSession | None = None,
    doc_ids: list[uuid.UUID] | None = None,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
    prior_summaries: list[dict] | None = None,
    supplement_points: list[dict] | None = None,
    benchmark_high_risk: list[dict] | None = None,
    glossary: list[dict] | None = None,
    extra_instruction: str = "",
    stop_event: asyncio.Event | None = None,
) -> str:
    """生成单个章节内容.

    context: 调用方（retrieve 节点）传入的 RAG 检索素材；为空时尝试内部检索兜底。
    db: 调用方传入的真实 DB session；未传入时兜底检索自行打开 session。
    doc_ids: 资料库挂载配置 — 非 None 时兜底检索仅限定指定文档（None = 项目全量）。
    on_delta: 三期 S4 流式回调 — 非 None 时走流式生成并逐块回调，返回全文；
        None 时保持非流式调用（向后兼容）。
    prior_summaries: 已完成章节摘要 [{chapter_no, title, summary}]，注入提示词防重复保衔接。
    supplement_points: 大纲未覆盖的 confirmed 评分点，注入提示词要求本章补写。
    benchmark_high_risk（阶段 D）：高风险评分点 [{clause_no, strategy}]，注入对标要点段。
    glossary（阶段 E2）：术语表 [{term, canonical, desc}]，注入提示词统一用语。
    extra_instruction（阶段 2）：用户自定义提示词，脱敏后追加到用户提示词末尾。
    stop_event（阶段 2）：流式取消令牌，置位后中止并返回已累积部分。
    """

    chapter_title = chapter.get("title", "")
    sections = flatten_sections(chapter.get("sections", []))

    # RAG 检索相关资料（优先使用调用方传入的检索素材）
    if not context:
        try:
            from app.core.database import async_session_factory
            from app.services.llm.rag_service import get_embedding, retrieve_with_rerank

            query = f"{chapter_title} {' '.join(sections)}"
            query_embedding = await get_embedding(query)
            if db is not None:
                similar_chunks = await retrieve_with_rerank(
                    db=db,
                    project_id=project_id,
                    query=query,
                    query_embedding=query_embedding,
                    top_k=10,
                    doc_ids=doc_ids,
                )
            else:
                async with async_session_factory() as session:
                    similar_chunks = await retrieve_with_rerank(
                        db=session,
                        project_id=project_id,
                        query=query,
                        query_embedding=query_embedding,
                        top_k=10,
                        doc_ids=doc_ids,
                    )
            context = "\n\n---\n\n".join(c.content for c in similar_chunks)
        except Exception:
            context = ""  # RAG 失败时降级为无上下文

    # 构造评分点覆盖
    sp_text = ""
    for sp in score_points:
        sp_text += f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
        sp_text += f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}\n"

    # 构造技术需求覆盖
    tr_text = ""
    for tr in tech_requirements:
        tr_text += f"- [{tr.get('category', '')}] {tr.get('description', '')}\n"

    # RAG 语料拼接提示词前脱敏（外发 LLM 安全铁律）
    context = redact(context)

    # 已完成章节摘要（防重复保衔接）；同样脱敏后外发
    if prior_summaries:
        prior_text = "\n".join(
            f"- 第{p.get('chapter_no', '')}章 {p.get('title', '')}: {p.get('summary', '')}"
            for p in prior_summaries
        )
        prior_text = redact(prior_text)
    else:
        prior_text = "（无，本章为全文首章）"

    # 大纲未覆盖评分点补写指令（覆盖矩阵）；同样脱敏后外发
    if supplement_points:
        supp_lines = [
            f"- {sp.get('clause_no', '')} {sp.get('item', '')}: "
            f"分值{sp.get('score', '?')}, 标准: {sp.get('criteria', '')}"
            for sp in supplement_points
        ]
        supp_text = redact("\n".join(supp_lines))
    else:
        supp_text = "（无，已确认评分点均已被大纲覆盖）"

    # 阶段 D：高风险评分点对标要点注入（1.4）；脱敏后外发
    if benchmark_high_risk:
        hr_text = redact(
            "\n".join(
                f"- {p.get('clause_no', '')}: {p.get('strategy', '')}" for p in benchmark_high_risk
            )
        )
    else:
        hr_text = ""

    # 阶段 E2：术语表注入（统一用语）；脱敏后外发
    if glossary:
        gl_text = redact(
            "\n".join(
                f"- {g.get('term', '')} → {g.get('canonical', '')}"
                for g in glossary
                if g.get("term") and g.get("canonical")
            )
        )
    else:
        gl_text = ""

    system_prompt, user_prompt = load_chapter_prompt(
        chapter_title=chapter_title,
        sections=sections,
        context=context,
        score_points=sp_text,
        tech_requirements=tr_text,
        prior_summaries=prior_text,
        supplement_points=supp_text,
        benchmark_high_risk=hr_text,
        glossary=gl_text,
    )

    # 阶段 2：用户自定义提示词（辅助生成）——脱敏后追加，不外泄敏感信息
    if extra_instruction.strip():
        user_prompt += f"\n\n【用户补充要求】\n{redact(extra_instruction.strip())}"

    if on_delta is not None:
        # 三期 S4：流式生成 — 逐块回调 delta，累积全文返回（stop_event 置位后中止保留已累积部分）
        parts: list[str] = []
        async for delta in call_llm_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            stop_event=stop_event,
        ):
            parts.append(delta)
            await on_delta(delta)
        return "".join(parts)

    content = await call_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.7,
    )

    return content


# ───────────────────────── 章节落库（Phase 4 从 agents/nodes/_shared.py 迁入） ─────────────────────────


async def upsert_section(
    db,
    project_id: str,
    section_id: str,
    title: str,
    content_md: str,
    status: str = "draft",
    citations: list | None = None,
) -> None:
    """保存章节到 proposal_sections（upsert）；citations 为引用溯源元数据."""
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
        if citations is not None:
            section.citations = citations
        db.add(section)
    else:
        section.title = title
        section.content_md = content_md
        section.status = status
        if citations is not None:
            section.citations = citations
    await db.flush()


async def persist_chapter_content(
    db,
    project_id: str,
    chapter_no: str,
    title: str,
    content: str,
    status: str = "draft",
    sections_tree: list | None = None,
    citations: list | None = None,
) -> None:
    """章节落库统一入口：章级行（全文）+ 嵌套大纲时切分子节行.

    state.chapters 保持章级全文（检索/摘要用），proposal_sections 子节行为
    子节真源（子节分工/编辑粒度）；string[] 大纲仅写章级行（向后兼容）。
    citations：检索命中溯源元数据，写章级行供导出标注。
    """
    await upsert_section(
        db, project_id, chapter_no, title, content, status=status, citations=citations
    )
    for sec in split_chapter_to_sections(content, sections_tree or [], chapter_no):
        await upsert_section(
            db, project_id, sec["section_id"], sec["title"], sec["content"], status=status
        )
