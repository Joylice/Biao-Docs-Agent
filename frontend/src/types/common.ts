/** 通用类型定义：API 响应、分页、枚举等 */

/** 统一 API 响应结构 */
export interface ApiResponse<T = unknown> {
  code: number
  data: T
  message?: string
}

/** 分页列表响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page?: number
  page_size?: number
}

/** 分页请求参数 */
export interface PaginationParams {
  page?: number
  page_size?: number
}

/** 任务状态枚举（分工/章节通用） */
export type TaskStatus = 'pending' | 'in_progress' | 'rejected' | 'submitted' | 'approved'

/** 任务状态元信息 */
export const TASK_STATUS_META: Record<TaskStatus, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

/** 工作流阶段 */
export type WorkflowPhase = 'init' | 'parse' | 'generate' | 'review' | 'export' | 'done'

/** 工作流阶段中文映射 */
export const PHASE_META: Record<string, string> = {
  init: '待启动',
  parse: '解析中',
  generate: '生成中',
  generating: '生成中',
  review: '审阅阶段',
  export: '导出中',
  done: '已完成',
}

/** 风险等级 */
export type RiskLevel = 'high' | 'mid' | 'low'

/** 风险等级元信息 */
export const RISK_META: Record<RiskLevel, { text: string; color: string }> = {
  high: { text: '高', color: 'red' },
  mid: { text: '中', color: 'orange' },
  low: { text: '低', color: 'default' },
}

/** 知识库范围 */
export type KbScope = 'personal' | 'project' | 'company'

/** 知识库范围中文映射 */
export const KB_SCOPE_LABEL: Record<KbScope, string> = {
  company: '公司',
  project: '项目',
  personal: '个人',
}
