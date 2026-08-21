/** 用户、角色、权限相关类型 */

/** 当前用户信息 */
export interface CurrentUser {
  id: string
  email: string
  display_name: string
  role?: string
  permissions?: string[]
}

/** 角色枚举（对齐后端 member/kb_admin/admin） */
export type UserRole = 'member' | 'kb_admin' | 'admin'

/** 用户列表项（对齐后端 UserListOut） */
export interface UserItem {
  id: string
  email: string
  display_name: string
  role: UserRole
  created_at: string
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
  /** 兼容旧后端：与 username 同值发送 */
  email?: string
  password: string
}

/** 登录响应 */
export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: CurrentUser
}

/** 权限点目录项（GET /rbac/permissions） */
export interface PermissionCatalogItem {
  code: string
  name: string
  category: string
}

/** 权限点 */
export type Permission =
  | 'system:manage'
  | 'kb:read'
  | 'kb:write'
  | 'project:create'
  | 'project:read'
  | 'project:write'
  | 'project:delete'
