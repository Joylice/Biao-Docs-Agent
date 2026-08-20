/** 用户管理相关 API */
import api from './client'
import type { ApiResponse, PaginatedResponse, PaginationParams, UserItem, UserOption } from '@/types'

/** 获取用户列表 */
export const fetchUsers = (params?: PaginationParams & { keyword?: string; role?: string }) =>
  api.get<ApiResponse<PaginatedResponse<UserItem>>>('/users', { params })

/** 获取用户下拉选项 */
export const fetchUserOptions = () =>
  api.get<ApiResponse<PaginatedResponse<UserOption>>>('/users/options')

/** 获取用户详情 */
export const fetchUser = (userId: string) =>
  api.get<ApiResponse<UserItem>>(`/users/${userId}`)

/** 创建用户 */
export const createUser = (data: { email: string; password: string; display_name: string; role?: string }) =>
  api.post<ApiResponse<UserItem>>('/users', data)

/** 更新用户 */
export const updateUser = (userId: string, data: { display_name?: string; role?: string; status?: string }) =>
  api.put<ApiResponse<UserItem>>(`/users/${userId}`, data)

/** 删除用户 */
export const deleteUser = (userId: string) =>
  api.delete<ApiResponse<void>>(`/users/${userId}`)

/** 重置用户密码 */
export const resetUserPassword = (userId: string, newPassword: string) =>
  api.post<ApiResponse<void>>(`/users/${userId}/reset-password`, { password: newPassword })
