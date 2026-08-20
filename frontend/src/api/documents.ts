/** 文档/资料库相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  PaginationParams,
  DocumentItem,
  KbSearchResult,
} from '@/types'

/** 获取资料库文档列表（全局） */
export const fetchMaterials = (params?: PaginationParams & { category?: string; keyword?: string }) =>
  api.get<ApiResponse<PaginatedResponse<DocumentItem>>>('/kb/materials', { params })

/** 获取项目文档列表 */
export const fetchProjectDocuments = (projectId: string, params?: PaginationParams) =>
  api.get<ApiResponse<PaginatedResponse<DocumentItem>>>(`/projects/${projectId}/documents`, { params })

/** 获取文档详情 */
export const fetchDocument = (documentId: string) =>
  api.get<ApiResponse<DocumentItem>>(`/documents/${documentId}`)

/** 上传文档（返回上传 URL 或直接上传） */
export const uploadDocument = (projectId: string | undefined, formData: FormData) => {
  const url = projectId ? `/projects/${projectId}/documents` : '/kb/materials'
  return api.post<ApiResponse<DocumentItem>>(url, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 删除文档 */
export const deleteDocument = (documentId: string) =>
  api.delete<ApiResponse<void>>(`/documents/${documentId}`)

/** 更新文档元信息 */
export const updateDocument = (documentId: string, data: { title?: string; category?: string; tags?: string[] }) =>
  api.put<ApiResponse<DocumentItem>>(`/documents/${documentId}`, data)

/** 知识库搜索 */
export const searchKb = (params: {
  query: string
  project_id?: string
  kb_base_ids?: string[]
  top_k?: number
}) =>
  api.post<ApiResponse<KbSearchResult[]>>('/kb/search', params)

/** 重新索引文档 */
export const reindexDocument = (documentId: string) =>
  api.post<ApiResponse<void>>(`/documents/${documentId}/reindex`)
