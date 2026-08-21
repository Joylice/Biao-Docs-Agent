/** 文档、资料库、知识库相关类型 */
import type { KbScope } from './common'

/** 文档/资料项（对齐后端 /kb/materials 与项目文档列表输出） */
export interface DocumentItem {
  id: string
  title: string
  doc_type: string
  status: string
  project_id?: string | null
  category?: string | null
  tags?: string[]
  file_size?: number
  uploader_name?: string
  uploader_id?: string | null
  created_at: string
  updated_at?: string
}

/** 上传文档请求 */
export interface UploadDocumentRequest {
  project_id?: string
  category?: string
  tags?: string[]
}

/** 素材语义检索结果项（GET /kb/materials/search） */
export interface MaterialSearchItem {
  title: string
  content: string
  score?: number
}

/** 知识库（对齐后端 kb-bases 列表输出） */
export interface KnowledgeBase {
  id: string
  name: string
  scope: KbScope
  description?: string | null
  material_count: number
  project_id?: string | null
  /** 项目库附带的项目名 */
  project_name?: string | null
  owner_id?: string | null
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
