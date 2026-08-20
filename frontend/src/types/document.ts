/** 文档、资料库、知识库相关类型 */
import type { KbScope } from './common'

/** 文档/资料项 */
export interface DocumentItem {
  id: string
  title: string
  doc_type: string
  status: string
  project_id?: string | null
  category?: string
  tags?: string[]
  file_size?: number
  created_at: string
  updated_at?: string
}

/** 上传文档请求 */
export interface UploadDocumentRequest {
  project_id?: string
  category?: string
  tags?: string[]
}

/** 知识库 */
export interface KnowledgeBase {
  id: string
  name: string
  scope: KbScope
  description?: string
  material_count: number
  project_id?: string
  created_at?: string
}

/** 知识库分块 */
export interface KbChunk {
  id: string
  document_id: string
  content: string
  chunk_index: number
  metadata?: Record<string, unknown>
}

/** 知识库搜索结果 */
export interface KbSearchResult {
  chunk_id: string
  document_id: string
  document_title: string
  content: string
  score: number
  metadata?: Record<string, unknown>
}

/** 文档状态 */
export type DocumentStatus = 'uploading' | 'parsing' | 'ready' | 'failed'

/** 文档状态元信息 */
export const DOCUMENT_STATUS_META: Record<DocumentStatus, { text: string; color: string }> = {
  uploading: { text: '上传中', color: 'processing' },
  parsing: { text: '解析中', color: 'processing' },
  ready: { text: '已就绪', color: 'success' },
  failed: { text: '失败', color: 'error' },
}
