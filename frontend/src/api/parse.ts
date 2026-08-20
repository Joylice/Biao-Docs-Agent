/** 招标解析相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  ScorePoint,
  TechRequirement,
  TenderDocItem,
  FormatRequirementItem,
} from '@/types'

/** 获取评分点列表 */
export const fetchScorePoints = (projectId: string, params?: { confirmed?: boolean }) =>
  api.get<ApiResponse<PaginatedResponse<ScorePoint>>>(`/projects/${projectId}/score-points`, { params })

/** 确认评分点 */
export const confirmScorePoint = (projectId: string, pointId: string, confirmed: boolean) =>
  api.put<ApiResponse<ScorePoint>>(`/projects/${projectId}/score-points/${pointId}`, { confirmed })

/** 批量确认评分点 */
export const batchConfirmScorePoints = (projectId: string, ids: string[], confirmed: boolean) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/score-points/batch-confirm`, { ids, confirmed })

/** 保存评分点应对策略 */
export const saveScorePointStrategy = (projectId: string, pointId: string, strategy: string) =>
  api.put<ApiResponse<ScorePoint>>(`/projects/${projectId}/score-points/${pointId}/strategy`, {
    strategy,
  })

/** 批量设置应对策略 */
export const batchSetScorePointStrategy = (projectId: string, ids: string[], strategy: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/score-points/batch-strategy`, { ids, strategy })

/** 获取技术需求列表 */
export const fetchTechRequirements = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<TechRequirement>>>(`/projects/${projectId}/tech-requirements`)

/** 确认技术需求 */
export const confirmTechRequirement = (projectId: string, reqId: string, confirmed: boolean) =>
  api.put<ApiResponse<TechRequirement>>(`/projects/${projectId}/tech-requirements/${reqId}`, {
    confirmed,
  })

/** 获取招标文件信息 */
export const fetchTenderDoc = (projectId: string) =>
  api.get<ApiResponse<TenderDocItem>>(`/projects/${projectId}/tender-doc`)

/** 下载招标文件 */
export const downloadTenderDoc = (projectId: string) =>
  api.get(`/projects/${projectId}/tender-doc/download`, { responseType: 'blob' })

/** 重新解析招标文件 */
export const reparseTender = (projectId: string, force = false) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/reparse`, { force })

/** 获取格式要求列表 */
export const fetchFormatRequirements = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<FormatRequirementItem>>>(
    `/projects/${projectId}/format-requirements`,
  )

/** 保存格式要求 */
export const saveFormatRequirement = (projectId: string, data: Partial<FormatRequirementItem>) =>
  api.post<ApiResponse<FormatRequirementItem>>(`/projects/${projectId}/format-requirements`, data)

/** 删除格式要求 */
export const deleteFormatRequirement = (projectId: string, reqId: string) =>
  api.delete<ApiResponse<void>>(`/projects/${projectId}/format-requirements/${reqId}`)
