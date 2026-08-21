/** 招标解析相关 API */
import api from './client'
import type {
  ApiResponse,
  ScorePoint,
  TechRequirement,
  DocFormatRequirementItem,
  DisqualificationClause,
} from '@/types'

/** 获取评分点列表（后端返回数组） */
export const fetchScorePoints = (projectId: string) =>
  api.get<ApiResponse<ScorePoint[]>>(`/projects/${projectId}/score-points`)

/** 更新评分点（strategy / confirmed 均可选，对齐后端 ScorePointUpdate） */
export const updateScorePoint = (
  projectId: string,
  pointId: string,
  data: { strategy?: string | null; confirmed?: boolean },
) =>
  api.put<ApiResponse<ScorePoint>>(`/projects/${projectId}/score-points/${pointId}`, data)

/** 获取技术需求列表（后端返回数组） */
export const fetchTechRequirements = (projectId: string) =>
  api.get<ApiResponse<TechRequirement[]>>(`/projects/${projectId}/tech-requirements`)

/** 获取技术需求列表（含 source/related_sp 映射信息，后端返回数组） */
export const fetchRequirements = (projectId: string) =>
  api.get<ApiResponse<TechRequirement[]>>(`/projects/${projectId}/requirements`)

/** 梳理生成技术需求（score_point_ids 省略取全部已确认评分点） */
export const generateRequirements = (projectId: string, scorePointIds: string[]) =>
  api.post<ApiResponse<{ total: number; mapped: number }>>(
    `/projects/${projectId}/requirements/generate`,
    { score_point_ids: scorePointIds },
  )

/** 下载项目文档（字节流） */
export const downloadProjectDocument = (projectId: string, documentId: string) =>
  api.get(`/projects/${projectId}/documents/${documentId}/download`, { responseType: 'blob' })

/** 重新解析文档 */
export const reparseDocument = (projectId: string, documentId: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/documents/${documentId}/reparse`)

/** 获取文档格式要求 */
export const fetchDocFormatRequirements = (projectId: string, documentId: string) =>
  api.get<ApiResponse<{ items: DocFormatRequirementItem[] }>>(
    `/projects/${projectId}/documents/${documentId}/format-requirements`,
  )

/** 保存文档格式要求（全量覆盖） */
export const saveDocFormatRequirements = (
  projectId: string,
  documentId: string,
  items: DocFormatRequirementItem[],
) =>
  api.put<ApiResponse<{ items: DocFormatRequirementItem[] }>>(
    `/projects/${projectId}/documents/${documentId}/format-requirements`,
    { format_requirements: items },
  )

/** 获取文档废标条款 */
export const fetchDocDisqualificationClauses = (projectId: string, documentId: string) =>
  api.get<ApiResponse<{ items: DisqualificationClause[] }>>(
    `/projects/${projectId}/documents/${documentId}/disqualification-clauses`,
  )

/** 保存文档废标条款（全量覆盖） */
export const saveDocDisqualificationClauses = (
  projectId: string,
  documentId: string,
  items: DisqualificationClause[],
) =>
  api.put<ApiResponse<void>>(
    `/projects/${projectId}/documents/${documentId}/disqualification-clauses`,
    { items },
  )
