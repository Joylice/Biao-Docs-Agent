/** 用户管理相关 API */
import api from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  PaginationParams,
  UserItem,
  UserOption,
  PermissionCatalogItem,
} from '@/types'

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

/** 更新用户（PATCH；display_name/role 均可选） */
export const updateUser = (userId: string, data: { display_name?: string; role?: string }) =>
  api.patch<ApiResponse<UserItem>>(`/users/${userId}`, data)

/** 变更用户角色 */
export const updateUserRole = (userId: string, role: string) =>
  api.put<ApiResponse<UserItem>>(`/users/${userId}/role`, { role })

/** 重置用户密码 */
export const resetUserPassword = (userId: string, newPassword: string) =>
  api.put<ApiResponse<void>>(`/users/${userId}/password`, { password: newPassword })

/** 删除用户 */
export const deleteUser = (userId: string) =>
  api.delete<ApiResponse<void>>(`/users/${userId}`)

/** 获取权限点目录（仅系统管理员） */
export const fetchPermissionCatalog = () =>
  api.get<ApiResponse<{ items: PermissionCatalogItem[] }>>('/rbac/permissions')

/** 获取角色权限码列表 */
export const fetchRolePermissionCodes = (role: string) =>
  api.get<ApiResponse<{ codes: string[] }>>(`/rbac/roles/${role}/permissions`)

/** 全量覆盖角色权限码 */
export const updateRolePermissionCodes = (role: string, codes: string[]) =>
  api.put<ApiResponse<{ codes: string[] }>>(`/rbac/roles/${role}/permissions`, { codes })
