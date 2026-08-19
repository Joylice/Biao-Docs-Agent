/**
 * 当前登录用户角色与权限点状态（三期 S1：角色细分；阶段 A：权限点驱动）.
 *
 * 模块级单例 ref：AppLayout 拉取 /auth/me 时写入，各页面按权限点/角色控制入口展示。
 * 后端已做权限兜底（403），此处仅控制 UI 可见性。
 */
import { computed, ref } from 'vue'
import api from '@/api/client'

export type UserRole = 'member' | 'kb_admin' | 'admin'

export const currentRole = ref<UserRole>('member')

/** 当前登录用户 ID（/auth/me 写入；项目 owner 标记 / 成员管理用） */
export const currentUserId = ref('')

/** 当前登录用户全部功能权限点（/auth/me 的 data.permissions 写入；阶段 A 菜单/守卫驱动） */
export const currentPermissions = ref<string[]>([])

/** 系统管理员：用户管理 / 审计日志 / 模型设置 */
export const isAdmin = computed(() => currentRole.value === 'admin')

/** 资料库管理员：全局资料删除 / 编辑（admin 天然包含） */
export const isKbAdmin = computed(() => currentRole.value === 'admin' || currentRole.value === 'kb_admin')

export function setRole(role: string | undefined | null) {
  currentRole.value = (role as UserRole) || 'member'
}

/** 写入当前用户 ID（/auth/me 成功时调用） */
export function setCurrentUser(id: string | undefined | null) {
  currentUserId.value = id || ''
}

/** 写入当前用户功能权限点（/auth/me 成功时调用） */
export function setCurrentPermissions(codes: string[] | undefined | null) {
  currentPermissions.value = codes || []
}

/** 当前用户是否具备指定功能权限点（菜单可见性 / 路由守卫判定） */
export function hasPerm(code: string): boolean {
  return currentPermissions.value.includes(code)
}

/** 刷新角色与权限点（角色变更后调用；失败静默，401 由 client 拦截器统一处理） */
export async function fetchCurrentUserRole(): Promise<void> {
  try {
    const { data } = await api.get('/auth/me')
    if (data.code === 0) {
      setRole(data.data?.role)
      currentUserId.value = data.data?.id || ''
      setCurrentPermissions(data.data?.permissions)
    }
  } catch {
    // ignore
  }
}
