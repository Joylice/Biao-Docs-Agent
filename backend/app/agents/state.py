"""LangGraph 状态定义 — 对齐 SDD §6."""

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict


class BidState(TypedDict, total=False):
    """LangGraph 图状态（TypedDict，langgraph 1.x 推荐写法）."""

    # ── 基础信息 ──
    project_id: str
    user_id: str

    # ── 招标解析结果（图内由 parse 节点从 DB 读取）──
    score_points: list[dict]
    tech_requirements: list[dict]
    project_name: str
    tender_no: str
    # 阶段 E2 术语表：[{term, canonical, desc}]，parse 节点从招标文件 meta 载入
    glossary: list[dict]

    # ── 大纲 ──
    outline: list[dict]  # [{chapter_no, title, sections: [...]}]

    # ── 资料库挂载（confirm_outline 提交：None=项目全量 / []=不挂载 / 列表=指定文档）──
    mounted_doc_ids: list[str] | None
    # 知识库级挂载（2026-08-18：库级与文档级并集生效，均为 None 时项目全量）
    mounted_kb_ids: list[str] | None

    # ── 章节生成（逐章合并）──
    chapters: Annotated[dict[str, str], operator.or_]
    current_chapter: str
    retrieved_context: str  # 当前章节 RAG 检索素材
    # 阶段 E3 引用溯源：当前章节检索命中 [{chunk_id, doc_title, page_no}]，随章节落库
    retrieved_citations: list[dict]
    validate_retries: int  # 校验失败重试计数（≤2）
    validation_ok: bool
    # 章节间上下文：{chapter_no: {title, summary}}，每章生成后提取 ≤200 字摘要
    chapter_summaries: Annotated[dict[str, dict], operator.or_]

    # ── 全文一致性检查（integrate 前）──
    consistency_issues: list[dict]  # [{chapter_no, type, description, fixable}]
    consistency_retried: bool  # 已走过一轮定向重写（最多 1 次）

    # ── 审阅（HITL resume 结果）──
    review_action: str  # approved | feedback
    review_feedback: dict  # {chapter_no: comment}

    # ── 导出 ──
    export_storage_key: str
    export_status: str  # pending|generating|done|failed

    # ── 流程控制 ──
    current_phase: str  # init|parse|confirm|outline|generate|review|export|done
    error: str
    progress: float
    regenerate_requested: bool  # confirm_outline 请求重新生成大纲（图边路由标记）


@dataclass
class TenderState:
    """投标方案生成工作流状态（dataclass，兼容历史测试/序列化）."""

    # ── 基础信息 ──
    project_id: str = ""
    user_id: str = ""

    # ── 招标解析结果 ──
    tender_text: str = ""
    score_points: list[dict] = field(default_factory=list)
    tech_requirements: list[dict] = field(default_factory=list)
    project_name: str = ""
    tender_no: str = ""

    # ── 人工确认 ──
    score_points_confirmed: bool = False

    # ── 大纲 ──
    outline: list[dict] = field(default_factory=list)  # [{chapter_no, title, sections: [...]}]
    outline_confirmed: bool = False

    # ── 章节生成 ──
    chapters: dict[str, str] = field(default_factory=dict)  # {chapter_no: content}
    current_chapter: str = ""  # 当前正在生成的章节号

    # ── 审阅 ──
    review_comments: list[dict] = field(default_factory=list)  # [{chapter_no, comment, action}]
    revised_chapters: dict[str, str] = field(default_factory=dict)

    # ── 导出 ──
    export_storage_key: str = ""
    export_status: str = ""  # pending|generating|done|failed

    # ── 流程控制 ──
    current_phase: str = "init"  # init|parse|confirm|outline|generate|review|export|done
    error: str = ""
    progress: float = 0.0  # 0.0 ~ 1.0

    def to_dict(self) -> dict[str, Any]:
        """转为字典（用于 LangGraph state channel）."""
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "tender_text": self.tender_text,
            "score_points": self.score_points,
            "tech_requirements": self.tech_requirements,
            "project_name": self.project_name,
            "tender_no": self.tender_no,
            "score_points_confirmed": self.score_points_confirmed,
            "outline": self.outline,
            "outline_confirmed": self.outline_confirmed,
            "chapters": self.chapters,
            "current_chapter": self.current_chapter,
            "review_comments": self.review_comments,
            "revised_chapters": self.revised_chapters,
            "export_storage_key": self.export_storage_key,
            "export_status": self.export_status,
            "current_phase": self.current_phase,
            "error": self.error,
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenderState":
        """从字典恢复状态."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
