/** 项目相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  PaginationParams,
  Project,
  CreateProjectRequest,
  ProjectMember,
} from '@/types'

/** 获取项目列表 */
export const fetchProjects = (params?: PaginationParams) =>
  api.get<ApiResponse<PaginatedResponse<Project>>>('/projects', { params })

/** 获取项目详情 */
export const fetchProject = (projectId: string) =>
  api.get<ApiResponse<Project>>(`/projects/${projectId}`)

/** 创建项目 */
export const createProject = (data: CreateProjectRequest) =>
  api.post<ApiResponse<Project>>('/projects', data)

/** 更新项目 */
export const updateProject = (projectId: string, data: Partial<CreateProjectRequest>) =>
  api.put<ApiResponse<Project>>(`/projects/${projectId}`, data)

/** 删除项目 */
export const deleteProject = (projectId: string) =>
  api.delete<ApiResponse<void>>(`/projects/${projectId}`)

/** 获取项目成员列表 */
export const fetchProjectMembers = (projectId: string) =>
  api.get<ApiResponse<PaginatedResponse<ProjectMember>>>(`/projects/${projectId}/members`)

/** 添加项目成员 */
export const addProjectMember = (projectId: string, email: string) =>
  api.post<ApiResponse<ProjectMember>>(`/projects/${projectId}/members`, { email })

/** 移除项目成员 */
export const removeProjectMember = (projectId: string, userId: string) =>
  api.delete<ApiResponse<void>>(`/projects/${projectId}/members/${userId}`)
