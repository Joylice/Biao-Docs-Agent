import api from './client'

/** GET /settings/llm 返回的模型配置（密钥为脱敏串） */
export interface LlmSettings {
  deepseek_api_key: string
  dashscope_api_key: string
  llm_model: string
  llm_api_base: string
  embedding_api_base: string
  embedding_model: string
  embedding_api_key: string
  llm_mock: boolean
  deepseek_configured: boolean
  dashscope_configured: boolean
  embedding_configured: boolean
}

/** PUT /settings/llm 请求体（密钥/自定义模型字段三态：字段省略=保持原值，空字符串=清除，非空=更新；embedding_api_base/embedding_model 与 llm_mock 必填全量） */
export interface LlmSettingsPayload {
  deepseek_api_key?: string
  dashscope_api_key?: string
  llm_model?: string
  llm_api_base?: string
  embedding_api_base: string
  embedding_model: string
  embedding_api_key?: string
  llm_mock: boolean
}

/** 连通性测试目标 */
export type ConnectionTestTarget = 'llm' | 'embedding'

/** POST /settings/llm/test 返回结果（HTTP 恒 200） */
export interface ConnectionTestResult {
  ok: boolean
  model?: string
  latency_ms?: number
  dimension?: number
  error?: string
}

/** 后端统一响应包装 */
interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

export const getLlmSettings = async (): Promise<LlmSettings> => {
  const { data } = await api.get<ApiResult<LlmSettings>>('/settings/llm')
  return data.data
}

export const updateLlmSettings = async (payload: LlmSettingsPayload): Promise<void> => {
  await api.put<ApiResult<null>>('/settings/llm', payload)
}

export const testLlmConnection = async (
  target: ConnectionTestTarget,
): Promise<ConnectionTestResult> => {
  const { data } = await api.post<ApiResult<ConnectionTestResult>>('/settings/llm/test', {
    target,
  })
  return data.data
}
