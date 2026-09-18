import api from './client'

/** 检索配置（从 /settings/llm 读取 embedding 部分） */
export interface RetrievalConfig {
  embedding_model: string
  embedding_api_base: string
  embedding_api_key: string
  embedding_configured: boolean
  llm_mock: boolean
}

/** 检索参数（v2 优先从 DB /settings/retrieval 读取，回退 localStorage） */
export interface RetrievalParams {
  recallTopK: number
  similarityThreshold: number
  hybridWeight: number
}

/** DB 检索参数（从 /settings/retrieval 读取） */
export interface RetrievalParamsDB {
  recall_top_k: number
  similarity_threshold: number
  hybrid_weight: number
  rerank_enabled: boolean
  rerank_model: string
  rerank_top_k: number
  rerank_api_key: string
  rerank_configured: boolean
}

/** 索引统计 */
export interface IndexStats {
  totalDocs: number
  totalChunks: number
  dimension: number
  indexSize: string
}

interface ApiResult<T> {
  code: number
  message?: string
  data: T
}

/** 获取检索配置（复用 /settings/llm 的 embedding 字段） */
export const getRetrievalConfig = async (): Promise<RetrievalConfig> => {
  const { data } = await api.get<ApiResult<RetrievalConfig>>('/settings/llm')
  const d = data.data
  return {
    embedding_model: d.embedding_model || '',
    embedding_api_base: d.embedding_api_base || '',
    embedding_api_key: d.embedding_api_key || '',
    embedding_configured: d.embedding_configured || false,
    llm_mock: d.llm_mock || false,
  }
}

/** 更新 embedding 配置（复用 /settings/llm PUT，只发 embedding 字段） */
export const updateRetrievalConfig = async (payload: {
  embedding_api_base: string
  embedding_model: string
  embedding_api_key?: string
  llm_mock: boolean
}): Promise<void> => {
  await api.put<ApiResult<null>>('/settings/llm', payload)
}

/** 连通性测试 */
export const testRetrievalConnection = async (): Promise<{
  ok: boolean
  dimension?: number
  error?: string
}> => {
  const { data } = await api.post<ApiResult<{ ok: boolean; dimension?: number; error?: string }>>(
    '/settings/llm/test',
    { target: 'embedding' },
  )
  return data.data
}

/** localStorage 回退 key（DB 不可达时使用） */
const PARAMS_KEY = 'bid-retrieval-params'

/** 获取检索参数：优先从 DB /settings/retrieval 读取，失败回退 localStorage */
export const getRetrievalParams = async (): Promise<RetrievalParams> => {
  try {
    const { data } = await api.get<ApiResult<RetrievalParamsDB>>('/settings/retrieval')
    const d = data.data
    return {
      recallTopK: d.recall_top_k,
      similarityThreshold: d.similarity_threshold,
      hybridWeight: d.hybrid_weight,
    }
  } catch {
    // DB 不可达，回退 localStorage
    const stored = localStorage.getItem(PARAMS_KEY)
    if (stored) {
      try {
        return JSON.parse(stored)
      } catch {
        // fallthrough to defaults
      }
    }
    return { recallTopK: 20, similarityThreshold: 0.35, hybridWeight: 0.7 }
  }
}

/** 保存检索参数到 DB（/settings/retrieval PUT），同时写 localStorage 做双保险 */
export const saveRetrievalParams = async (params: RetrievalParams): Promise<void> => {
  // localStorage 双写（DB 不可达时前端仍可回退）
  localStorage.setItem(PARAMS_KEY, JSON.stringify(params))
  // DB 持久化
  await api.put<ApiResult<null>>('/settings/retrieval', {
    recall_top_k: params.recallTopK,
    similarity_threshold: params.similarityThreshold,
    hybrid_weight: params.hybridWeight,
  })
}

/** PUT /settings/retrieval 请求体（变更字段才携带；rerank_api_key 三态：省略=保持/''=清除/非空=更新，对齐后端 RetrievalConfigUpdate） */
export interface RetrievalParamsUpdate {
  recall_top_k?: number
  similarity_threshold?: number
  hybrid_weight?: number
  rerank_enabled?: boolean
  rerank_model?: string
  rerank_top_k?: number
  rerank_api_key?: string
}

/** 获取检索设置原始视图（含 rerank 配置与脱敏密钥；配置中心 T03 用） */
export const getRetrievalSettings = async (): Promise<RetrievalParamsDB> => {
  const { data } = await api.get<ApiResult<RetrievalParamsDB>>('/settings/retrieval')
  return data.data
}

/** 更新检索设置（/settings/retrieval PUT，仅管理员；配置中心 T03 用） */
export const updateRetrievalParams = async (payload: RetrievalParamsUpdate): Promise<void> => {
  await api.put<ApiResult<null>>('/settings/retrieval', payload)
}

/** 触发全量索引重建（POST /settings/retrieval/reindex，异步任务） */
export const reindexAll = async (): Promise<{ enqueued: boolean; message: string }> => {
  const { data } = await api.post<ApiResult<{ enqueued?: boolean }>>('/settings/retrieval/reindex')
  return {
    enqueued: data.data?.enqueued !== false,
    message: data.message || '索引重建任务已入队',
  }
}
