/** 分工/章节编制相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  AssignmentNode,
  AssistRequest,
} from '@/types'

/** 章节内容：content 为 Markdown 文本；content_html 为富文本 HTML（后端双字段扩展） */
export interface ChapterContent {
  content: string
  content_html?: string
}

/** 获取章节分工列表（树形） */
export const fetchChapterAssignments = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<AssignmentNode>>>(`/projects/${projectId}/chapter-assignments`)

/** 批量推送章节分工（后端幂等 upsert，响应同为树形结构） */
export const upsertChapterAssignments = (
  projectId: string,
  assignments: Array<{ chapter_no: string; title: string; assignee_id: string }>,
) =>
  api.post<ApiResponse<PaginatedResponse<AssignmentNode>>>(
    `/projects/${projectId}/chapter-assignments`,
    assignments,
  )

/** 领取任务：pending/rejected → in_progress（仅 assignee） */
export const acceptAssignment = (projectId: string, assignmentId: string) =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/accept`,
  )

/** 提交审核：in_progress/rejected → submitted（仅 assignee） */
export const submitAssignment = (projectId: string, assignmentId: string) =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/submit`,
  )

/** 审核通过：submitted → approved（仅 owner；comment 可选，缺省 body 仅 action） */
export const approveAssignment = (projectId: string, assignmentId: string, comment?: string) =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/review`,
    comment === undefined ? { action: 'approved' } : { action: 'approved', comment },
  )

/** 审核打回：submitted → rejected（仅 owner；body 对齐后端 ReviewBody） */
export const rejectAssignment = (projectId: string, assignmentId: string, comment: string) =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/review`,
    { action: 'rejected', comment },
  )

/** 获取章节内容（content_html 为后端扩展字段，可能缺省） */
export const fetchChapterContent = (projectId: string, chapterNo: string) =>
  api.get<ApiResponse<ChapterContent>>(`/projects/${projectId}/chapters/${chapterNo}/content`)

/**
 * 保存章节内容：PUT body 双字段 { content, content_html }
 * content=Markdown（与旧版兼容）；content_html=富文本 HTML（后端 0018 迁移扩展，缺省时仅传 content）
 */
export const saveChapterContent = (
  projectId: string,
  chapterNo: string,
  payload: ChapterContent,
) =>
  api.put<ApiResponse<ChapterContent>>(
    `/projects/${projectId}/chapters/${chapterNo}/content`,
    payload,
  )

/** AI 辅助编写 */
export const assistChapter = (projectId: string, data: AssistRequest) =>
  api.post<ApiResponse<{ content: string }>>(`/projects/${projectId}/chapters/assist`, data)
