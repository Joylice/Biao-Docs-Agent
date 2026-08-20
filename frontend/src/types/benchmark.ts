/** 评分点对标、废标条款相关类型 */
import type { RiskLevel } from './common'

/** 评分对标项 */
export interface BenchmarkItem {
  clause_no: string
  item: string
  score: number
  criteria: string
  strategy: string
  /** 素材覆盖度 0~1 */
  coverage: number
  risk: RiskLevel
}

/** 评分对标列定义 */
export const BENCHMARK_COLUMNS = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 100 },
  { title: '评分项', dataIndex: 'item', key: 'item', width: 180 },
  { title: '分值', dataIndex: 'score', key: 'score', width: 70 },
  { title: '判定标准', dataIndex: 'criteria', key: 'criteria', ellipsis: { showTitle: true } },
  { title: '素材覆盖度', key: 'coverage', width: 160 },
  { title: '风险', key: 'risk', width: 80 },
  { title: '应对策略', key: 'strategy', width: 280 },
]

/** 废标条款 */
export interface DisqualificationClause {
  id: string
  clause_no: string
  title: string
  risk_category: string
  severity: string
  recommendation: string
  confirmed: boolean
  project_id?: string
  created_at?: string
}

/** 废标条款风险类别标签 */
export const DISQUALIFICATION_RISK_CATEGORY_LABELS: Record<string, string> = {
  qualification: '资格要求',
  technical: '技术要求',
  commercial: '商务要求',
  delivery: '交付要求',
  other: '其他',
}

/** 废标条款严重程度元信息 */
export const DISQUALIFICATION_SEVERITY_META: Record<string, { text: string; color: string }> = {
  high: { text: '高风险', color: 'red' },
  medium: { text: '中风险', color: 'orange' },
  low: { text: '低风险', color: 'default' },
}

/** 废标条款确认请求 */
export interface ConfirmDisqualificationRequest {
  confirmed: boolean
}
