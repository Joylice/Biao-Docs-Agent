/** 分工/章节编制相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  AssignmentItem,
  AssignmentNode,
  AssistRequest,
} from '@/types'

/** 获取章节分工列表（树形） */
export const fetchChapterAssignments = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<AssignmentNode>>>(`/projects/${projectId}/chapter-assignments`)

/** 获取分工列表（扁平） */
export const fetchAssignments = (projectId: string, params?: { status?: string; assignee_id?: string }) =>
  api.get<ApiResponse<PaginatedResponse<AssignmentItem>>>(`/projects/${projectId}/assignments`, { params })

/** 分配章节 */
export const assignChapter = (projectId: string, chapterNo: string, assigneeId: string) =>
  api.post<ApiResponse<AssignmentItem>>(`/projects/${projectId}/assignments`, {
    chapter_no: chapterNo,
    assignee_id: assigneeId,
  })

/** 批量分配章节 */
export const batchAssignChapters = (
  projectId: string,
  assignments: Array<{ chapter_no: string; assignee_id: string }>,
) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/assignments/batch`, { assignments })

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

/** 审核通过：submitted → approved（仅 owner；body 对齐后端 ReviewBody） */
export const approveAssignment = (projectId: string, assignmentId: string, comment = '') =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/review`,
    { action: 'approved', comment },
  )

/** 审核打回：submitted → rejected（仅 owner；body 对齐后端 ReviewBody） */
export const rejectAssignment = (projectId: string, assignmentId: string, comment: string) =>
  api.post<ApiResponse<{ id: string; status: string }>>(
    `/projects/${projectId}/chapter-assignments/${assignmentId}/review`,
    { action: 'rejected', comment },
  )

/** 获取章节内容 */
export const fetchChapterContent = (projectId: string, chapterNo: string) =>
  api.get<ApiResponse<{ content: string }>>(`/projects/${projectId}/chapters/${chapterNo}/content`)

/** 保存章节内容 */
export const saveChapterContent = (projectId: string, chapterNo: string, content: string) =>
  api.put<ApiResponse<void>>(`/projects/${projectId}/chapters/${chapterNo}/content`, { content })

/** AI 辅助编写 */
export const assistChapter = (projectId: string, data: AssistRequest) =>
  api.post<ApiResponse<{ content: string }>>(`/projects/${projectId}/chapters/assist`, data)

/** 上传章节图片 */
export const uploadChapterImage = (projectId: string, chapterNo: string, formData: FormData) =>
  api.post<ApiResponse<{ url: string }>>(
    `/projects/${projectId}/chapters/${chapterNo}/images`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
