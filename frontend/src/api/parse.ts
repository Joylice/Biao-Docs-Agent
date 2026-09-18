/** 招标解析相关 API */
import api from './client'
import type {
  ApiResponse,
  ScorePoint,
  DocFormatRequirementItem,
  DisqualificationClause,
  ParseWarning,
  GlossaryItem,
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

/** 获取解析交叉校验告警（P2 — validator Agent 产出，存 doc.meta） */
export const fetchParseWarnings = (projectId: string, documentId: string) =>
  api.get<ApiResponse<{ items: ParseWarning[]; count: number }>>(
    `/projects/${projectId}/documents/${documentId}/parse-warnings`,
  )

/** 获取文档术语表（只读，存 doc.meta.glossary） */
export const fetchDocGlossary = (projectId: string, documentId: string) =>
  api.get<ApiResponse<{ items: GlossaryItem[] }>>(
    `/projects/${projectId}/documents/${documentId}/glossary`,
  )
