/** 工作流相关 API */
import api from './client'
import type {
  ApiResponse,
  WorkflowStatus,
  ConfirmOutlineRequest,
  OutlineDraft,
  OutlineSuggestion,
  SectionSuggestion,
} from '@/types'

/** 获取工作流状态 */
export const fetchWorkflowStatus = (projectId: string) =>
  api.get<ApiResponse<WorkflowStatus>>(`/projects/${projectId}/workflow/status`)

/** 确认评分点（启动工作流） */
export const confirmScorePoints = (projectId: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/workflow/confirm-score-points`)

/** 确认大纲（启动章节生成） */
export const confirmOutline = (projectId: string, data: ConfirmOutlineRequest) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/workflow/confirm-outline`, data)

/** 重新生成大纲 */
export const regenerateOutline = (projectId: string) =>
  api.post<ApiResponse<void>>(`/projects/${projectId}/workflow/regenerate-outline`)

/** 获取大纲草稿 */
export const fetchOutlineDraft = (projectId: string) =>
  api.get<ApiResponse<OutlineDraft>>(`/projects/${projectId}/workflow/outline-draft`)

/** 保存大纲草稿 */
export const saveOutlineDraft = (projectId: string, data: OutlineDraft) =>
  api.put<ApiResponse<void>>(`/projects/${projectId}/workflow/outline-draft`, data)

/** 删除大纲草稿 */
export const deleteOutlineDraft = (projectId: string) =>
  api.delete<ApiResponse<void>>(`/projects/${projectId}/workflow/outline-draft`)

/** 获取大纲优化建议 */
export const fetchOutlineSuggestions = (projectId: string) =>
  api.post<ApiResponse<{ suggestions: OutlineSuggestion[] }>>(
    `/projects/${projectId}/workflow/outline-suggest`,
  )

/** 应用大纲优化建议 */
export const applyOutlineSuggestions = (projectId: string, adopted: string[]) =>
  api.post<ApiResponse<{ outline: unknown[] }>>(
    `/projects/${projectId}/workflow/outline-suggest/apply`,
    { adopted },
  )

/** 获取章节内容改进建议 */
export const fetchSectionSuggestions = (projectId: string, chapterNo?: string) =>
  api.post<ApiResponse<{ suggestions: SectionSuggestion[] }>>(
    `/projects/${projectId}/workflow/section-suggest`,
    { chapter_no: chapterNo },
  )

/** 重写章节 */
export const rewriteChapter = (projectId: string, chapterNo: string, comment: string) =>
  api.post<ApiResponse<{ content: string }>>(
    `/projects/${projectId}/workflow/rewrite-chapter`,
    null,
    { params: { chapter_no: chapterNo, comment } },
  )
