import api from './client'

/** Provider 视图（GET /settings/providers 返回） */
export interface Provider {
  id: string
  name: string
  prefix: string
  apiKeyMasked: string
  configured: boolean
  apiBase: string
  defaultBase: string
  capabilities: {
    text: boolean
    embedding: boolean
    rerank: boolean
    vision: boolean
  }
  builtin: boolean
  enabled: boolean
  models: string[]
}

/** Model Route 视图（GET /settings/routes 返回） */
export interface ModelRoute {
  id: string
  stageKey: string
  stageName: string
  nodeName: string
  model: string
  fallback: string[]
  thinking: boolean
  temperature: number | null
  maxTokens: number | null
  timeout: number | null
  hint: string
  enabled: boolean
}

/** Provider 创建请求 */
export interface ProviderCreatePayload {
  name: string
  prefix: string
  api_key?: string
  api_base?: string
  capabilities?: string[]
  models?: string
}

/** Provider 更新请求 */
export interface ProviderUpdatePayload {
  name?: string
  api_key?: string
  api_base?: string
  enabled?: boolean
  capabilities?: string[]
  models?: string
}

/** Route 更新请求 */
export interface RouteUpdatePayload {
  model?: string
  fallback?: string[]
  thinking?: boolean
  temperature?: number
  max_tokens?: number
  timeout?: number
  hint?: string
  enabled?: boolean
}

interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

export const getProviders = async (): Promise<Provider[]> => {
  const { data } = await api.get<ApiResult<Provider[]>>('/settings/providers')
  return data.data
}

export const createProvider = async (payload: ProviderCreatePayload): Promise<Provider> => {
  const { data } = await api.post<ApiResult<Provider>>('/settings/providers', payload)
  return data.data
}

export const updateProvider = async (id: string, payload: ProviderUpdatePayload): Promise<Provider> => {
  const { data } = await api.put<ApiResult<Provider>>(`/settings/providers/${id}`, payload)
  return data.data
}

export const deleteProvider = async (id: string): Promise<void> => {
  await api.delete<ApiResult<null>>(`/settings/providers/${id}`)
}

export const getRoutes = async (): Promise<ModelRoute[]> => {
  const { data } = await api.get<ApiResult<ModelRoute[]>>('/settings/routes')
  return data.data
}

export const updateRoute = async (stageKey: string, payload: RouteUpdatePayload): Promise<ModelRoute> => {
  const { data } = await api.put<ApiResult<ModelRoute>>(`/settings/routes/${stageKey}`, payload)
  return data.data
}
