"""大纲节点 — generate_outline（LLM 生成落库）+ confirm_outline（HITL 确认/重生成）."""

import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.models.proposal import ProposalSkeleton


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


async def generate_outline_node(state: dict) -> dict:
    """节点：生成大纲 — 基于 state 中的评分点和技术需求，落库 proposal_skeletons.

    2026-08-26 单一数据源重构：generate_outline 改纯 state 读，regenerate 路径
    经独立 refresh_context 节点从 DB 刷新源数据写回 state，本节点不再直接读 DB。
    评分点仅 confirmed=true（refresh_context 已过滤），技术需求排除资格/商务类
    （refresh_context 已过滤），避免"企业资质与业绩""人员配置"等非技术章节混入大纲。
    """
    from app.services.infra.prompt_loader import load_outline_prompt
    from app.services.llm.llm_service import call_llm_with_schema

    project_id = state.get("project_id", "")
    # 纯 state 读（单一数据源：refresh_context 已从 DB 刷新并过滤）
    score_points = state.get("score_points", [])
    tech_requirements = state.get("tech_requirements", [])
    project_name = state.get("project_name", "")
    tender_no = state.get("tender_no", "")
    industry = state.get("industry", "")

    system_prompt, user_prompt = load_outline_prompt(
        score_points=score_points,
        tech_requirements=tech_requirements,
        project_name=project_name,
        tender_no=tender_no,
        industry=industry,
    )

    try:
        llm_result = await call_llm_with_schema(
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
        outline = llm_result.get("chapters", [])
        if not outline:
            return {
                "error": "大纲生成为空",
                "current_phase": "confirm",
                "regenerate_requested": False,
            }

        async with _pkg.async_session_factory() as db:
            await _pkg._upsert_skeleton(db, project_id, outline)
            await _pkg._update_workflow(
                db, project_id, phase="outline", progress=0.35, status="waiting"
            )
            await db.commit()  # BUG-2：skeleton + workflow 写入显式提交
        await _pkg.publish_event(
            project_id, {"type": "progress", "phase": "outline", "progress": 0.35}
        )
        return {
            "outline": outline,
            "current_phase": "outline",
            "progress": 0.35,
            "outline_context_version": state.get("context_version"),
        }
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
    - True / {"confirmed": True} → 确认大纲，进入章节生成（缺省 start_generation=True）
    - {"confirmed": True, "start_generation": False} → 确认后停靠「待分工」
      （wait_division interrupt），章节内容由分工页编制，审核通过后回写正式方案
    - {"confirmed": True, "outline": [...]} → 采用前端二次编辑后的大纲
      （替换 state.outline 并落库 proposal_skeletons），随后进入章节生成/待分工
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
            # 写入 checkpoint，以保证 state 与 DB 落库一致），生成后回本节点再次挂起；
            # 不再内联调用 generate_outline_node（普通函数返回不经图，曾致 state 陈旧）
            if decision.get("action") == "regenerate":
                # regenerate：作废旧章节（reducer 空 dict = 清空），经图边回
                # refresh_context → generate_outline
                return {
                    "regenerate_requested": True,
                    "current_phase": "outline",
                    "chapters": {},
                    "chapter_summaries": {},
                    "current_chapter": "",
                    "validate_retries": 0,
                    "validation_ok": False,
                }
            # 前端二次编辑后的大纲：替换 state.outline 并落库（DB 与 state 一致）
            if "outline" in decision and decision["outline"] is not None:
                state = {**state, "outline": decision["outline"]}
                async with _pkg.async_session_factory() as db:
                    await _pkg._upsert_skeleton(
                        db, state.get("project_id", ""), decision["outline"]
                    )
                    await db.commit()
            # 资料库挂载配置（None = 项目全量，[] = 不挂载）
            if "mounted_doc_ids" in decision:
                state = {**state, "mounted_doc_ids": decision["mounted_doc_ids"]}
            # 知识库级挂载配置（与文档级并集生效，见 resolve_mount_doc_ids）
            if "mounted_kb_ids" in decision:
                state = {**state, "mounted_kb_ids": decision["mounted_kb_ids"]}
        confirmed = decision is True or (
            isinstance(decision, dict) and decision.get("confirmed") is True
        )
        if not confirmed:
            return {
                "error": "大纲未确认",
                "current_phase": "outline",
                "regenerate_requested": False,
            }
        # 2026-08-25：start_generation 缺省 True 保持旧行为（测试直接 resume True 兼容）
        start_generation = (
            decision.get("start_generation", True)
            if isinstance(decision, dict)
            else True
        )
        # 确认成功：清除二次编辑草稿（独立 DB 写；防陈旧草稿下次误恢复）
        async with _pkg.async_session_factory() as db:
            await _pkg._clear_outline_draft(db, state.get("project_id", ""))
            await db.commit()
        updates: dict = {
            "current_phase": "generate" if start_generation else "division",
            "progress": 0.4 if start_generation else 0.45,
            "validate_retries": 0,
            "outline": state.get("outline", []),
            "regenerate_requested": False,
        }
        # 挂载配置仅在显式提交过时写入 state（缺省 None 保持项目全量检索）
        if "mounted_doc_ids" in state:
            updates["mounted_doc_ids"] = state["mounted_doc_ids"]
        if "mounted_kb_ids" in state:
            updates["mounted_kb_ids"] = state["mounted_kb_ids"]
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
