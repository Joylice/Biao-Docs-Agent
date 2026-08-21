/** 审阅、批注、版本相关类型 */

/** 审阅章节树节点 */
export interface ReviewChapterNode {
  key: string
  title: string
  chapter_no: string
  children?: ReviewChapterNode[]
}

/** 版本项（对齐后端 versions 列表输出） */
export interface VersionItem {
  id: string
  version: number
  snapshot_note: string | null
  created_by: string | null
  created_by_name: string | null
  auto: boolean
  created_at: string | null
}

/** 批注项（对齐后端章节批注输出） */
export interface AnnotationItem {
  id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string | null
}

/** 创建批注请求（章节号在路径中） */
export interface CreateAnnotationRequest {
  content: string
}

/** 更新批注请求 */
export interface UpdateAnnotationRequest {
  content?: string
}

/** 废标风险项（审阅页按章节展示，对齐 /disqualification-risks 条目） */
export interface DisqualificationRisk {
  clause_no: string
  title: string
  severity: string
  risk_category: string
  recommendation: string
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

/** 创建快照请求（对齐后端 SnapshotBody） */
export interface SnapshotRequest {
  snapshot_note: string | null
}

/** 归档到知识库请求（对齐后端 ArchiveBody） */
export interface ArchiveToKbRequest {
  kb_id: string
}
