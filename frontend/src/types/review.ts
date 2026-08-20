/** 审阅、标注、版本相关类型 */

/** 审阅章节树节点 */
export interface ReviewChapterNode {
  key: string
  title: string
  chapter_no: string
  children?: ReviewChapterNode[]
}

/** 版本项 */
export interface VersionItem {
  id: string
  project_id: string
  version_no: number
  note: string
  created_by: string
  created_by_name: string
  created_at: string
  chapter_count: number
  word_count: number
}

/** 标注项 */
export interface AnnotationItem {
  id: string
  project_id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string
  resolved: boolean
  resolved_at?: string
  resolved_by?: string
}

/** 创建标注请求 */
export interface CreateAnnotationRequest {
  chapter_no: string
  content: string
}

/** 更新标注请求 */
export interface UpdateAnnotationRequest {
  content?: string
  resolved?: boolean
}

/** 审阅反馈请求 */
export interface ReviewFeedbackRequest {
  chapter_no: string
  comment: string
  action: 'approve' | 'reject'
}

/** 章节审阅状态 */
export type ChapterReviewStatus = 'pending' | 'approved' | 'rejected' | 'needs_revision'

/** 章节审阅状态元信息 */
export const CHAPTER_REVIEW_STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待审阅', color: 'default' },
  approved: { text: '已通过', color: 'success' },
  rejected: { text: '已打回', color: 'error' },
  needs_revision: { text: '需修改', color: 'warning' },
}

/** 导出状态 */
export type ExportStatus = 'idle' | 'generating' | 'done' | 'failed'

/** 导出请求 */
export interface ExportRequest {
  format: 'docx' | 'pdf'
  template_id?: string
  include_annotations?: boolean
}

/** 导出响应 */
export interface ExportResponse {
  task_id: string
  status: ExportStatus
  download_url?: string
  file_name?: string
  file_size?: number
  created_at?: string
}

/** 快照请求 */
export interface SnapshotRequest {
  note: string
}

/** 归档到知识库请求 */
export interface ArchiveToKbRequest {
  version_id: string
  kb_base_id: string
}
