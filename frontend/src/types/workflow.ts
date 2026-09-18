/** 工作流、大纲、章节生成相关类型 */
import type { WorkflowPhase, TaskStatus } from './common'

/** 大纲节（字符串或嵌套树） */
export type OutlineSection = string | { title: string; children?: OutlineSection[] }

/** 大纲项（章节） */
export interface OutlineItem {
  chapter_no: string
  title: string
  sections?: OutlineSection[]
  covered_clauses?: string[]
}

/** 大纲编辑树节点 */
export interface OutlineTreeNode {
  key: string
  title: string
  covered_clauses?: string[]
  children?: OutlineTreeNode[]
}

/** 工作流中断信息 */
export interface WorkflowInterrupt {
  type: string
  data?: Record<string, unknown>
  /** AI 自动审阅意见（review 节点 interrupt 前一轮 LLM 输出） */
  auto_comments?: AutoReviewComment[]
}

/** 工作流状态 */
export interface WorkflowStatus {
  phase: WorkflowPhase | string
  interrupt?: WorkflowInterrupt | null
  outline?: OutlineItem[]
  chapters?: Record<string, string>
  progress: number
  current_chapter?: string
  /** 审阅阶段动作（后端 workflow status 透出） */
  review_action?: string
  /** 章节审阅反馈意见（章节号 → 意见） */
  review_feedback?: Record<string, string>
  /** AI 自动审阅意见（review 节点 interrupt 前一轮 LLM 输出） */
  review_comments?: AutoReviewComment[]
  /** 导出状态：pending/running/done/failed */
  export_status?: string
  /** 导出产物存储标识 */
  export_storage_key?: string
  /** 工作流错误信息 */
  error?: string
}

/** 确认大纲请求 */
export interface ConfirmOutlineRequest {
  outline: OutlineItem[]
  mounted_doc_ids?: string[] | null
  mounted_kb_ids?: string[] | null
  /** 2026-08-25：是否确认后自动批量生成章节；false（默认）由分工驱动编制 */
  start_generation?: boolean
}

/** 审阅确认请求（通过 / 章节反馈重写） */
export interface ConfirmReviewRequest {
  action: 'approved' | 'feedback'
  /** action=feedback 时：章节号 → 修改意见 */
  feedback?: Record<string, string>
}

/** 大纲草稿 */
export interface OutlineDraft {
  outline: OutlineItem[]
  mounted_doc_ids?: string[] | null
  mounted_kb_ids?: string[] | null
  updated_at?: string
}

/** 大纲优化建议 */
export interface OutlineSuggestion {
  suggestion_id: string
  suggestion_type: 'add_section' | 'add_chapter' | 'rename' | 'merge'
  target: Record<string, string>
  reason: string
  suggested_action: string
}

/** 大纲建议类型元信息 */
export const OUTLINE_SUGGEST_TYPE_META: Record<string, { color: string; label: string }> = {
  add_section: { color: 'blue', label: '补充小节' },
  add_chapter: { color: 'green', label: '新增章节' },
  rename: { color: 'orange', label: '修改标题' },
  merge: { color: 'purple', label: '合并章节' },
}

/** 章节内容改进建议 */
export interface SectionSuggestion {
  chapter_no: string
  issue: string
  suggestion: string
  severity: string
}

/** 重写章节请求 */
export interface RewriteChapterRequest {
  chapter_no: string
  comment: string
}

/** WebSocket 消息类型 */
export type WsMessageType =
  | 'progress'
  | 'section_token'
  | 'section_done'
  | 'done'
  | 'error'
  | 'ping'
  | 'pong'
  | `task_${string}`

/** WebSocket 进度消息 */
export interface WsProgressMessage {
  type: 'progress'
  progress: number
  current_chapter?: string
  chapters?: Record<string, string>
}

/** WebSocket 流式 token 消息 */
export interface WsSectionTokenMessage {
  type: 'section_token'
  chapter_no: string
  delta?: string
}

/** WebSocket 章节完成消息 */
export interface WsSectionDoneMessage {
  type: 'section_done'
  chapter_no: string
  content: string
}

/** 分工树节点 */
export interface AssignmentNode {
  id: string | null
  chapter_no: string
  title: string
  assignee_id: string | null
  assignee_name: string | null
  status: TaskStatus | string | null
  children?: AssignmentNode[]
  /** 后端列表接口附带的提交人姓名（用于审阅页展示） */
  submitted_by_name?: string
}

/** 导出格式覆盖（前端自定义，传了哪个字段就用哪个，没传保留招标解析默认值） */
export interface FormatOverride {
  /** 正文字体（宋体/仿宋/黑体/楷体/微软雅黑） */
  body_font?: string
  /** 正文字号 pt（如 12=小四, 14=四号, 16=三号, 10.5=五号） */
  body_size_pt?: number
  /** 标题字号 pt（不传则沿用 heading 样式） */
  heading_size_pt?: number
  /** 行距倍数（1.0/1.15/1.5/2.0） */
  line_spacing?: number
  /** 固定行距 pt（与 line_spacing 二选一） */
  line_spacing_fixed_pt?: number
  /** 页边距 cm（仅传了的边覆盖） */
  margins_cm?: {
    top?: number
    bottom?: number
    left?: number
    right?: number
  }
}

/** 导出选项（传给后端驱动 Word 导出） */
export interface ExportOptions {
  /** 文档内容选项 */
  include_toc?: boolean
  include_annotations?: boolean
  include_header_footer?: boolean
  /** 页面设置 */
  paper_size?: 'A4' | 'A3'
  orientation?: 'portrait' | 'landscape'
  /** 导出范围 */
  scope?: 'all' | 'current'
  /** 当前章节号（scope=current 时必传） */
  current_chapter?: string
  /** 格式覆盖（字段级覆盖招标解析默认值） */
  format_override?: FormatOverride
}

/** AI 自动审阅意见（review 节点在 interrupt 前跑一轮 LLM 的输出） */
export interface AutoReviewComment {
  chapter_no: string
  comment: string
  action?: string
  severity?: string
}
