/** 审阅、标注、版本相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  VersionItem,
  AnnotationItem,
  CreateAnnotationRequest,
  UpdateAnnotationRequest,
  ExportRequest,
  ExportResponse,
  SnapshotRequest,
} from '@/types'

/** 获取版本列表 */
export const fetchVersions = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<VersionItem>>>(`/projects/${projectId}/versions`)

/** 获取版本详情 */
export const fetchVersion = (projectId: string, versionId: string) =>
  api.get<ApiResponse<VersionItem & { chapters: Record<string, string> }>>(
    `/projects/${projectId}/versions/${versionId}`,
  )

/** 创建快照 */
export const createSnapshot = (projectId: string, data: SnapshotRequest) =>
  api.post<ApiResponse<VersionItem>>(`/projects/${projectId}/versions`, data)

/** 回滚到版本 */
export const rollbackToVersion = (projectId: string, versionId: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/versions/${versionId}/rollback`)

/** 归档版本到知识库 */
export const archiveVersionToKb = (projectId: string, versionId: string, kbBaseId: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/versions/${versionId}/archive`, {
    kb_base_id: kbBaseId,
  })

/** 获取章节标注列表 */
export const fetchAnnotations = (projectId: string, chapterNo: string) =>
  api.get<ApiResponse<PaginatedResponse<AnnotationItem>>>(
    `/projects/${projectId}/annotations`,
    { params: { chapter_no: chapterNo } },
  )

/** 创建标注 */
export const createAnnotation = (projectId: string, data: CreateAnnotationRequest) =>
  api.post<ApiResponse<AnnotationItem>>(`/projects/${projectId}/annotations`, data)

/** 更新标注 */
export const updateAnnotation = (projectId: string, annotationId: string, data: UpdateAnnotationRequest) =>
  api.put<ApiResponse<AnnotationItem>>(`/projects/${projectId}/annotations/${annotationId}`, data)

/** 删除标注 */
export const deleteAnnotation = (projectId: string, annotationId: string) =>
  api.delete<ApiResponse<void>>(`/projects/${projectId}/annotations/${annotationId}`)

/** 提交审阅反馈 */
export const submitReviewFeedback = (
  projectId: string,
  chapterNo: string,
  action: 'approve' | 'reject',
  comment?: string,
) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/review/${chapterNo}`, { action, comment })

/** 导出文档 */
export const exportDocument = (projectId: string, data: ExportRequest) =>
  api.post<ApiResponse<ExportResponse>>(`/projects/${projectId}/export`, data)

/** 获取导出状态 */
export const fetchExportStatus = (projectId: string, taskId: string) =>
  api.get<ApiResponse<ExportResponse>>(`/projects/${projectId}/export/${taskId}`)

/** 下载导出文件 */
export const downloadExport = (projectId: string, taskId: string) =>
  api.get(`/projects/${projectId}/export/${taskId}/download`, { responseType: 'blob' })
