"""大纲节点 — generate_outline（LLM 生成落库）+ confirm_outline（HITL 确认/重生成）."""

import uuid

from sqlalchemy import select

import app.agents.nodes as _pkg  # 运行时经包查找可 patch 名（保持拆分前 monkeypatch 语义）
from app.agents.nodes._shared import logger
from app.models.project import Project
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


# 资格/商务类需求关键词：招标原文提取（source=NULL）的需求中含资质/业绩/财务等
# 资格条件内容，不属于技术方案应答范围，大纲生成时排除（2026-08-25）
_QUALIFICATION_KEYWORDS = (
    "资质",
    "业绩",
    "财务",
    "信誉",
    "注册证书",
    "职称",
    "证书",
    "许可证",
    "保证金",
    "投标报价",
    "合同金额",
    # 人员资格类（负责人/工程师/建造师等岗位配置要求）
    "负责人",
    "工程师",
    "建造师",
    "项目总工",
    "项目经理",
    "人员配备",
    "组织机构",
    "岗位",
)


def _is_qualification_req(desc: str) -> bool:
    """判断技术需求是否为资格/商务/人员配置类（命中关键词）."""
    if not desc:
        return False
    return any(kw in desc for kw in _QUALIFICATION_KEYWORDS)


async def _load_outline_inputs(
    project_id: str, state: dict
) -> tuple[list[dict], list[dict]]:
    """从 DB 重新读取大纲输入（评分点严格过滤 + 排除资格类需求）.

    2026-08-25 严格模式修复：regenerate 路径复用 checkpointer 旧 state（可能含
    未确认评分点/资格需求），此处改为每次重新读 DB——评分点仅 confirmed=true；
    技术需求排除资质/业绩/财务/信誉/证书类（保留 sp_derived 关联需求与纯技术通用需求）。
    DB 读取失败时降级用 state 原值（不阻塞生成）。
    """
    if not project_id:
        return state.get("score_points", []), state.get("tech_requirements", [])
    try:

        async with _pkg.async_session_factory() as db:
            _, _, sps, trs, _ = await _pkg._load_tender_context(db, project_id)
        # 排除资格/商务类技术需求（保留关联评分点的 sp_derived 与纯技术通用需求）
        trs = [tr for tr in trs if not _is_qualification_req(tr.get("description", ""))]
        return sps, trs
    except Exception:
        logger.warning("重新读取大纲输入失败，降级用 state 值")
        return state.get("score_points", []), state.get("tech_requirements", [])


async def generate_outline_node(state: dict) -> dict:
    """节点：生成大纲 — 基于评分点和技术需求，落库 proposal_skeletons.

    2026-08-25 严格模式修复：评分点/技术需求不再信任 state 中的旧值（工作流启动时
    读入，regenerate 路径可能复用严格模式上线前的全量数据），改为每次重新从 DB 读取：
    - 评分点仅取 confirmed=true（与技术需求梳理对齐，未确认评分点不进大纲）
    - 技术需求排除资格/商务类（资质/业绩/财务/信誉/人员证书，source=NULL 招标原文提取），
      避免"企业资质与业绩""人员配置"等非技术章节混入大纲
    """
    from app.services.infra.prompt_loader import load_outline_prompt
    from app.services.llm.llm_service import call_llm_with_schema

    project_id = state.get("project_id", "")
    # 从 DB 重新读取（严格过滤 + 排除资格需求）；读失败降级用 state 值
    score_points, tech_requirements = await _load_outline_inputs(project_id, state)

    # 阶段6：注入项目上下文（名称/招标编号/行业）；查询失败降级不阻塞生成
    project_name = tender_no = industry = ""
    if project_id:
        try:
            async with _pkg.async_session_factory() as db:
                result = await db.execute(
                    select(Project).where(Project.id == uuid.UUID(project_id))
                )
                project = result.scalar_one_or_none()
                if project is not None:
                    project_name = project.name or ""
                    tender_no = project.tender_no or ""
                    industry = project.industry or ""
        except Exception:
            logger.warning("获取项目上下文失败，降级为无上下文生成大纲")

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
                return {"regenerate_requested": True, "current_phase": "outline"}
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
