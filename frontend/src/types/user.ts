/** 用户、角色、权限相关类型 */

/** 当前用户信息 */
export interface CurrentUser {
  id: string
  email: string
  display_name: string
  role?: string
  permissions?: string[]
}

/** 用户列表项 */
export interface UserItem {
  id: string
  email: string
  display_name: string
  role?: string
  created_at?: string
  status?: string
}

/** 用户下拉选项 */
export interface UserOption {
  id: string
  email: string
  display_name: string
}

/** 登录请求（支持用户名或邮箱登录） */
export interface LoginRequest {
  username: string
  password: string
}

/** 登录响应 */
export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: CurrentUser
}

/** 角色枚举 */
export type UserRole = 'admin' | 'user'

/** 权限点 */
export type Permission =
  | 'system:manage'
  | 'kb:read'
  | 'kb:write'
  | 'project:create'
  | 'project:read'
  | 'project:write'
  | 'project:delete'
