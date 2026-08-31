/** 文档/资料库相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  PaginationParams,
  DocumentItem,
  KbSearchResult,
  MaterialSearchItem,
} from '@/types'

/** 资料列表查询参数（对齐后端 /kb/materials 查询项） */
export type MaterialListParams = PaginationParams & {
  category?: string
  keyword?: string
  tag?: string
  kb_id?: string
  scope?: string
}

/** 获取资料库文档列表（全局） */
export const fetchMaterials = (params?: MaterialListParams) =>
  api.get<ApiResponse<PaginatedResponse<DocumentItem>>>('/kb/materials', { params })

/** 上传素材（不手动设 Content-Type：axios 自动带 boundary） */
export const uploadMaterial = (formData: FormData) =>
  api.post<ApiResponse<DocumentItem>>('/kb/materials', formData)

/** 编辑素材元信息（title/category/tags，均可选） */
export const updateMaterial = (
  materialId: string,
  data: { title?: string; category?: string | null; tags?: string[] },
) => api.patch<ApiResponse<DocumentItem>>(`/kb/materials/${materialId}`, data)

/** 删除素材 */
export const deleteMaterial = (materialId: string) =>
  api.delete<ApiResponse<void>>(`/kb/materials/${materialId}`)

/** 下载素材（字节流） */
export const downloadMaterial = (materialId: string) =>
  api.get(`/kb/materials/${materialId}/download`, { responseType: 'blob' })

/** 素材语义检索 */
export const searchMaterials = (params: { q: string; top_k?: number }) =>
  api.get<ApiResponse<{ items: MaterialSearchItem[] }>>('/kb/materials/search', { params })

/** 获取项目文档列表（doc_type 可选过滤） */
export const fetchProjectDocuments = (
  projectId: string,
  params?: PaginationParams & { doc_type?: string },
) =>
  api.get<ApiResponse<PaginatedResponse<DocumentItem>>>(`/projects/${projectId}/documents`, {
    params,
  })

/** 上传招标文件（不手动设 Content-Type：axios 自动带 boundary） */
export const uploadTenderDocument = (
  projectId: string,
  formData: FormData,
  onUploadProgress?: (event: { loaded: number; total?: number }) => void,
) =>
  api.post<ApiResponse<DocumentItem>>(`/projects/${projectId}/documents`, formData, {
    params: { doc_type: 'tender_file' },
    onUploadProgress,
  })

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

/** 重新解析招标文件（清除旧评分点 → 状态重置 → 重新入队） */
export const reparseTenderDocument = (projectId: string, documentId: string) =>
  api.post<ApiResponse<DocumentItem>>(`/projects/${projectId}/documents/${documentId}/reparse`)
