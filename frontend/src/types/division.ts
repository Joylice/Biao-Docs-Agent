/** 分工、章节编制相关类型 */
import type { TaskStatus } from './common'
import type { OutlineSection } from './workflow'

/** 大纲项（分工页用） */
export interface DivisionOutlineItem {
  chapter_no: string
  title: string
  sections?: OutlineSection[]
  covered_clauses?: string[]
}

/** 分工项 */
export interface AssignmentItem {
  id: string
  project_id: string
  chapter_no: string
  title: string
  assignee_id: string | null
  assignee_name: string | null
  status: TaskStatus | string
  parent_chapter_no?: string | null
  created_at?: string
  updated_at?: string
  submitted_at?: string
  reviewed_at?: string
  review_comment?: string
}

/** 章节行（表格展示用） */
export interface ChapterRow {
  rowType: 'chapter'
  chapter_no: string
  title: string
  assignment?: AssignmentItem
  sections: SectionRow[]
  expanded: boolean
}

/** 节行（表格展示用） */
export interface SectionRow {
  rowType: 'section'
  chapter_no: string
  section_no: string
  title: string
  assignment?: AssignmentItem
}

/** 分工行（章节或节） */
export type DivisionRow = ChapterRow | SectionRow

/** 分配任务请求 */
export interface AssignTaskRequest {
  chapter_no: string
  assignee_id: string
}

/** 批量分配请求 */
export interface BatchAssignRequest {
  assignments: Array<{ chapter_no: string; assignee_id: string }>
}

/** 章节内容保存请求 */
export interface SaveChapterContentRequest {
  chapter_no: string
  content: string
}

/** AI 辅助请求 */
export interface AssistRequest {
  chapter_no: string
  prompt: string
  mode: 'append' | 'overwrite'
}

/** 审阅操作请求 */
export interface ReviewActionRequest {
  chapter_no: string
  action: 'approve' | 'reject'
  comment?: string
}

/** 分工状态元信息（与 common.TASK_STATUS_META 一致，此处提供别名） */
export const DIVISION_STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

/** 看板列定义 */
export interface KanbanColumn {
  key: TaskStatus
  title: string
  color: string
  items: AssignmentItem[]
}
