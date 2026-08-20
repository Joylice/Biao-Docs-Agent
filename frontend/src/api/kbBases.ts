/** 知识库（KbBase）相关 API */
import api from './client'
import type { ApiResponse, PaginatedResponse, PaginationParams, KnowledgeBase } from '@/types'

/** 获取知识库列表 */
export const fetchKbBases = (params?: PaginationParams & { project_id?: string; scope?: string }) =>
  api.get<ApiResponse<PaginatedResponse<KnowledgeBase>>>('/kb-bases', { params })

/** 获取知识库详情 */
export const fetchKbBase = (kbBaseId: string) =>
  api.get<ApiResponse<KnowledgeBase>>(`/kb-bases/${kbBaseId}`)

/** 创建知识库 */
export const createKbBase = (data: {
  name: string
  scope: 'personal' | 'project' | 'company'
  description?: string
  project_id?: string
}) => api.post<ApiResponse<KnowledgeBase>>('/kb-bases', data)

/** 更新知识库 */
export const updateKbBase = (kbBaseId: string, data: { name?: string; description?: string }) =>
  api.put<ApiResponse<KnowledgeBase>>(`/kb-bases/${kbBaseId}`, data)

/** 删除知识库 */
export const deleteKbBase = (kbBaseId: string) =>
  api.delete<ApiResponse<void>>(`/kb-bases/${kbBaseId}`)

/** 向知识库添加文档 */
export const addDocumentToKbBase = (kbBaseId: string, documentId: string) =>
  api.post<ApiResponse<void>>(`/kb-bases/${kbBaseId}/documents`, { document_id: documentId })

/** 从知识库移除文档 */
export const removeDocumentFromKbBase = (kbBaseId: string, documentId: string) =>
  api.delete<ApiResponse<void>>(`/kb-bases/${kbBaseId}/documents/${documentId}`)
