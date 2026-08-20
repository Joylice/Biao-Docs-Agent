/** 评分对标、废标条款相关 API */
import api from './client'
import type { ApiResponse, PaginatedResponse, BenchmarkItem, DisqualificationClause } from '@/types'

/** 获取评分对标列表 */
export const fetchBenchmark = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<BenchmarkItem>>>(`/projects/${projectId}/benchmark`)

/** 保存应对策略 */
export const saveBenchmarkStrategy = (projectId: string, clauseNo: string, strategy: string) =>
  api.put<ApiResponse<{ strategy: string }>>(
    `/projects/${projectId}/benchmark/${encodeURIComponent(clauseNo)}/strategy`,
    { strategy },
  )

/** 获取废标条款列表 */
export const fetchDisqualificationClauses = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<DisqualificationClause>>>(
    `/projects/${projectId}/disqualification-clauses`,
  )

/** 确认废标条款 */
export const confirmDisqualificationClause = (
  projectId: string,
  clauseId: string,
  confirmed: boolean,
) =>
  api.put<ApiResponse<DisqualificationClause>>(
    `/projects/${projectId}/disqualification-clauses/${clauseId}`,
    { confirmed },
  )

/** 批量确认废标条款 */
export const batchConfirmDisqualificationClauses = (
  projectId: string,
  ids: string[],
  confirmed: boolean,
) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/disqualification-clauses/batch-confirm`, {
    ids,
    confirmed,
  })
