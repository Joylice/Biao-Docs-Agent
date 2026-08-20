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
}

/** 工作流状态 */
export interface WorkflowStatus {
  phase: WorkflowPhase | string
  interrupt?: WorkflowInterrupt | null
  outline?: OutlineItem[]
  chapters?: Record<string, string>
  progress: number
  current_chapter?: string
}

/** 确认大纲请求 */
export interface ConfirmOutlineRequest {
  outline: OutlineItem[]
  mounted_doc_ids?: string[] | null
  mounted_kb_ids?: string[] | null
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
  delta: string
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
}
