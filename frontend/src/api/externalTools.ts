import api from './client'

/** 外部工具视图（GET /settings/external-tools 返回） */
export interface ExternalTool {
  id: string
  name: string
  preset: string
  toolType: string
  apiKeyMasked: string
  configured: boolean
  baseUrl: string
  timeoutMs: number
  maxQueryChars: number
  enabled: boolean
  version: number
  /** 已绑定的阶段 key 列表（GET /settings/external-tools 回填，供 SkillsPanel 首屏即展示关联） */
  boundStages?: string[]
}

/** 外部工具创建请求 */
export interface ToolCreatePayload {
  name: string
  preset: string
  tool_type?: string
  api_key?: string
  base_url?: string
  timeout_ms?: number
  max_query_chars?: number
  enabled?: boolean
}

/** 外部工具更新请求（密钥三态 + 乐观锁） */
export interface ToolUpdatePayload {
  name?: string
  api_key?: string
  base_url?: string
  timeout_ms?: number
  max_query_chars?: number
  enabled?: boolean
  expected_version: number
}

/** 绑定请求 */
export interface BindPayload {
  stage_key: string
}

/** 绑定关系视图 */
export interface ToolBinding {
  toolId: string
  stageKey: string
}

/** 后端统一响应包装 */
interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

export const getExternalTools = async (): Promise<ExternalTool[]> => {
  const { data } = await api.get<ApiResult<ExternalTool[]>>('/settings/external-tools')
  return data.data
}

export const createExternalTool = async (payload: ToolCreatePayload): Promise<ExternalTool> => {
  const { data } = await api.post<ApiResult<ExternalTool>>('/settings/external-tools', payload)
  return data.data
}

export const updateExternalTool = async (
  id: string,
  payload: ToolUpdatePayload,
): Promise<ExternalTool> => {
  const { data } = await api.put<ApiResult<ExternalTool>>(`/settings/external-tools/${id}`, payload)
  return data.data
}

export const deleteExternalTool = async (id: string): Promise<void> => {
  await api.delete<ApiResult<null>>(`/settings/external-tools/${id}`)
}

export const testExternalTool = async (id: string): Promise<unknown[]> => {
  const { data } = await api.post<ApiResult<unknown[]>>(`/settings/external-tools/${id}/test`)
  return data.data
}

export const bindExternalTool = async (id: string, payload: BindPayload): Promise<ToolBinding> => {
  const { data } = await api.put<ApiResult<ToolBinding>>(`/settings/external-tools/${id}/bind`, payload)
  return data.data
}

export const unbindExternalTool = async (id: string, stageKey: string): Promise<void> => {
  await api.delete<ApiResult<null>>(`/settings/external-tools/${id}/bind/${stageKey}`)
}
