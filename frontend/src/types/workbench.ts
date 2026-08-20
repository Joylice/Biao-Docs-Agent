/** 工作台相关类型 */
import type { TaskStatus, WorkflowPhase } from './common'

/** 工作台待办条目 */
export interface WorkbenchTaskItem {
  assignment_id: string
  project_id: string
  project_name: string
  chapter_no: string
  title: string
  status: TaskStatus | string
}

/** 工作台项目进度 */
export interface WorkbenchProjectProgress {
  project_id: string
  project_name: string
  total: number
  approved: number
  percent: number
  phase: WorkflowPhase | string
  status_dist: Partial<Record<TaskStatus, number>>
}

/** 工作台汇总数据 */
export interface WorkbenchSummary {
  tasks: Record<TaskStatus, WorkbenchTaskItem[]>
  my_projects: WorkbenchProjectProgress[]
  /** 仅项目 owner 且名下项目存在 submitted 分工时非空 */
  owner_review_pending: WorkbenchTaskItem[]
}

/** 工作台分桶顺序 */
export const WORKBENCH_BUCKET_ORDER: TaskStatus[] = [
  'pending',
  'in_progress',
  'rejected',
  'submitted',
  'approved',
]

/** 工作台分桶元信息 */
export const WORKBENCH_BUCKET_META: Record<TaskStatus, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}
