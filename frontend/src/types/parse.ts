/** 招标解析、评分点相关类型 */

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

/** 术语表条目（只读，对齐后端 doc.meta.glossary） */
export interface GlossaryItem {
  term: string
  canonical: string
  desc?: string
}

/** 解析交叉校验告警（P2 — validator Agent 产出，对齐后端 parse_warnings） */
export interface ParseWarning {
  type: string
  message: string
  severity: 'high' | 'mid' | 'low' | string
  agent_id?: string
}

/** 校验维度中文标签映射 */
export const WARNING_TYPE_LABELS: Record<string, string> = {
  duplicate: '重复条目',
  score_total: '分值合计',
  clause_no_format: '条款号格式',
  coverage: '覆盖',
  omission: '遗漏',
  format_term: '格式术语',
  degraded: '降级告警',
}

/** 告警严重程度颜色映射 */
export const warningSeverityColor = (severity: string): string => {
  const map: Record<string, string> = {
    high: 'red',
    mid: 'orange',
    low: 'blue',
  }
  return map[severity] || 'default'
}
