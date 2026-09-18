/**
 * useFormRules：配置中心表单校验共享 helpers（P1-6）.
 *
 * 纯函数、零框架依赖，供 useRetrievalConfig 等逻辑模型与面板复用；
 * 单测可直接覆盖边界值。密钥脱敏串判定复用 useProvidersConfig.isMaskedKey
 * （与后端 S-1 规则对齐）。
 */

export interface RangeRule {
  min: number
  max: number
  /** 错误消息中展示的字段名 */
  label: string
  /** 是否要求整数（Top-K 类参数） */
  integer?: boolean
}

/** 检索参数数值范围（PRD P1-6 / T03 定稿：recall_top_k 1~50） */
export const RETRIEVAL_RANGE_RULES = {
  recallTopK: { min: 1, max: 50, label: '召回 Top-K', integer: true },
  similarityThreshold: { min: 0, max: 1, label: '相似度阈值' },
  hybridWeight: { min: 0, max: 1, label: '混合检索权重' },
  rerankTopK: { min: 1, max: 20, label: '重排 Top-K', integer: true },
} as const satisfies Record<string, RangeRule>

export type RetrievalRangeKey = keyof typeof RETRIEVAL_RANGE_RULES

/**
 * api_base URL 校验：空串放行（可选字段），非空必须是合法 http(s) 完整 URL.
 * @returns 错误消息；合法返回 null
 */
export function validateApiUrl(value: string, label = '服务地址'): string | null {
  const v = value.trim()
  if (v === '') return null
  let url: URL
  try {
    url = new URL(v)
  } catch {
    return `${label}格式无效，需为 http(s):// 开头的完整 URL`
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return `${label}仅支持 http/https 协议`
  }
  return null
}

/**
 * 数值范围校验：null/undefined 视为未填写放行（可选参数，InputNumber 清空即 null/undefined）.
 * @returns 错误消息；合法返回 null
 */
export function validateRange(value: number | null | undefined, rule: RangeRule): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  if (rule.integer && !Number.isInteger(value)) {
    return `${rule.label}须为整数`
  }
  if (value < rule.min || value > rule.max) {
    return `${rule.label}取值范围 ${rule.min} ~ ${rule.max}`
  }
  return null
}
