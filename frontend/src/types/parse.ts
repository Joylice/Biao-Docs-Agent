/** 招标解析、评分点、技术需求相关类型 */

/** 评分点（对齐后端 ScorePointOut） */
export interface ScorePoint {
  id: string
  clause_no: string
  item: string
  score: number | null
  criteria: string | null
  is_star: boolean
  strategy: string | null
  risk_level: string | null
  confirmed: boolean
}

/** 技术需求（对齐后端 TechRequirementOut；/requirements 附带 source/related_sp） */
export interface TechRequirement {
  id: string
  seq: number
  description: string
  category: string | null
  is_mandatory: boolean
  /** /requirements 接口附带：来源评分点条款（未关联为 null） */
  source?: string | null
  /** /requirements 接口附带：关联评分点摘要 */
  related_sp?: { clause_no: string; item: string } | null
}

/** 文档级格式要求项（对齐后端 format-requirements 条目） */
export interface DocFormatRequirementItem {
  category: string
  requirement: string
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
