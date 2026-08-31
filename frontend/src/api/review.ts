/** 审阅、批注、版本相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  VersionItem,
  AnnotationItem,
  DisqualificationRisk,
} from '@/types'

/* ---------------- 版本 ---------------- */

/** 获取版本列表 */
export const fetchVersions = (projectId: string) =>
  api.get<ApiResponse<{ items: VersionItem[] }>>(`/projects/${projectId}/versions`)

/** 创建快照（备注可选，空串归一为 null） */
export const createSnapshot = (projectId: string, snapshotNote: string | null) =>
  api.post<ApiResponse<{ id: string; version: number }>>(`/projects/${projectId}/versions`, {
    snapshot_note: snapshotNote,
  })

/** 下载版本（type: docx=Word / source=Markdown 源，返回预签名 URL） */
export const downloadVersion = (projectId: string, versionId: string, type: 'docx' | 'source') =>
  api.get<ApiResponse<{ url?: string; storage_key?: string }>>(
    `/projects/${projectId}/versions/${versionId}/download`,
    { params: { type } },
  )

/** 获取版本 Markdown 源内容（用于差异比对） */
export const fetchVersionContent = (projectId: string, versionId: string) =>
  api.get<ApiResponse<{ content: string; version: number }>>(
    `/projects/${projectId}/versions/${versionId}/content`,
  )

/** 回滚到版本（仅 owner；返回恢复章节数） */
export const rollbackToVersion = (projectId: string, versionId: string) =>
  api.post<ApiResponse<{ id?: string; version?: number; chapters_restored?: number }>>(
    `/projects/${projectId}/versions/${versionId}/rollback`,
  )

/** 归档版本到公司知识库（body 对齐后端 ArchiveBody） */
export const archiveVersionToKb = (projectId: string, versionId: string, kbId: string) =>
  api.post<ApiResponse<{ title?: string }>>(
    `/projects/${projectId}/versions/${versionId}/archive`,
    { kb_id: kbId },
  )

/* ---------------- 章节批注 ---------------- */

/** 获取章节批注列表 */
export const fetchChapterAnnotations = (projectId: string, chapterNo: string) =>
  api.get<ApiResponse<PaginatedResponse<AnnotationItem>>>(
    `/projects/${projectId}/chapters/${chapterNo}/annotations`,
  )

/** 创建章节批注 */
export const createChapterAnnotation = (
  projectId: string,
  chapterNo: string,
  content: string,
  selection?: { from: number; to: number; text: string } | null,
) =>
  api.post<ApiResponse<AnnotationItem>>(
    `/projects/${projectId}/chapters/${chapterNo}/annotations`,
    { content, selection: selection || null },
  )

/** 更新章节批注 */
export const updateChapterAnnotation = (
  projectId: string,
  chapterNo: string,
  annotationId: string,
  content: string,
) =>
  api.put<ApiResponse<AnnotationItem>>(
    `/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}`,
    { content },
  )

/** 更新批注状态（open/resolved） */
export const updateAnnotationStatus = (
  projectId: string,
  chapterNo: string,
  annotationId: string,
  status: 'open' | 'resolved',
) =>
  api.patch<ApiResponse<AnnotationItem>>(
    `/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}/status`,
    { status },
  )

/** 删除章节批注 */
export const deleteChapterAnnotation = (projectId: string, chapterNo: string, annotationId: string) =>
  api.delete<ApiResponse<void>>(
    `/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}`,
  )

/* ---------------- 废标风险 ---------------- */

/** 获取废标风险（按章节分组） */
export const fetchDisqualificationRisks = (projectId: string) =>
  api.get<ApiResponse<{ risks: Record<string, DisqualificationRisk[]> }>>(
    `/projects/${projectId}/disqualification-risks`,
  )
