/** 招标解析、评分点、技术需求相关类型 */

/** 评分点 */
export interface ScorePoint {
  id: string
  clause_no: string
  item: string
  score: number | null
  criteria: string
  confirmed: boolean
  strategy?: string
  project_id?: string
  created_at?: string
}

/** 技术需求 */
export interface TechRequirement {
  id: string
  clause_no: string
  requirement: string
  category: string
  priority: string
  confirmed: boolean
  project_id?: string
}

/** 招标文件项 */
export interface TenderDocItem {
  id: string
  project_id: string
  file_name: string
  file_size: number
  status: string
  parsed_at?: string
  created_at: string
}

/** 格式要求项 */
export interface FormatRequirementItem {
  id: string
  category: string
  content: string
  project_id?: string
}

/** 格式要求类别 */
export const FORMAT_CATEGORIES: { value: string; label: string }[] = [
  { value: 'page', label: '页面设置' },
  { value: 'font', label: '字体规范' },
  { value: 'structure', label: '结构要求' },
  { value: 'content', label: '内容要求' },
  { value: 'binding', label: '装订要求' },
  { value: 'other', label: '其他' },
]

/** 评分点确认请求 */
export interface ConfirmScorePointRequest {
  confirmed: boolean
  strategy?: string
}

/** 批量确认评分点请求 */
export interface BatchConfirmScorePointsRequest {
  ids: string[]
  confirmed: boolean
}

/** 批量设置应对策略请求 */
export interface BatchSetStrategyRequest {
  ids: string[]
  strategy: string
}

/** 重新解析请求 */
export interface ReparseRequest {
  force?: boolean
}

/** 评分点风险颜色（分值 >= 20 为高风险） */
export const isHighScore = (score: number | null): boolean => (score ?? 0) >= 20

/** 技术需求优先级颜色 */
export const requirementPriorityColor = (priority: string): string => {
  const map: Record<string, string> = {
    high: 'red',
    medium: 'orange',
    low: 'default',
  }
  return map[priority] || 'default'
}
