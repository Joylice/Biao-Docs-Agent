/** 用户管理页共享类型与常量 */
import type { UserRole } from '@/stores/currentUser'

export interface UserItem {
  id: string
  email: string
  display_name: string
  role: UserRole
  created_at: string
}

/** 权限点目录项（GET /rbac/permissions） */
export interface PermItem {
  code: string
  name: string
  category: string
}

export const roleOptions = [
  { value: 'member', label: '普通成员' },
  { value: 'kb_admin', label: '资料库管理员' },
  { value: 'admin', label: '系统管理员' },
]

export const roleName: Record<string, string> = {
  member: '普通成员',
  kb_admin: '资料库管理员',
  admin: '系统管理员',
}

export const errMsg = (e: unknown, fallback: string) => {
  const err = e as { response?: { data?: { message?: string } } }
  return err?.response?.data?.message || fallback
}
