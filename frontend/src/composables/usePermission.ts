/**
 * 权限判定 composable（角色 + 权限点双维度控制）.
 *
 * 角色状态复用 stores/currentUser 模块级 ref（/auth/me 写入）；
 * 项目级判定由各页面拉取项目详情得到 owner_id 后传入比较。
 * 后端已做 403 兜底，此处仅控制前端入口可见性。
 *
 * 角色层级：admin > kb_admin > member
 * 权限点：system:manage / kb:read / kb:write / project:create / project:read / project:write / project:delete
 */
import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import {
  currentUserId,
  currentRole,
  currentPermissions,
  isAdmin as isAdminStore,
  isKbAdmin as isKbAdminStore,
} from '@/stores/currentUser'

/** 角色 → 默认权限点映射（后端 /auth/me 也会返回 permissions，此处作为前端兜底） */
const ROLE_PERMISSIONS: Record<string, string[]> = {
  admin: [
    'system:manage',
    'kb:read',
    'kb:write',
    'project:create',
    'project:read',
    'project:write',
    'project:delete',
  ],
  kb_admin: [
    'kb:read',
    'kb:write',
    'project:create',
    'project:read',
    'project:write',
  ],
  member: [
    'kb:read',
    'project:create',
    'project:read',
  ],
}

export interface UsePermissionReturn {
  /** 当前登录用户 ID */
  currentUserId: ComputedRef<string>
  /** 当前角色 */
  currentRole: ComputedRef<string>
  /** 系统管理员（用户管理 / 审计日志 / 模型设置） */
  isAdmin: ComputedRef<boolean>
  /** 资料库管理员（全局资料删除 / 编辑，admin 天然包含） */
  isKbAdmin: ComputedRef<boolean>
  /** 检查是否具备指定权限点（优先用后端返回的 permissions，兜底用角色映射） */
  can: (code: string) => boolean
  /** 当前用户是否为项目 owner（owner_id 与当前用户 ID 比较） */
  isProjectOwner: (projectOwnerId?: string | null) => boolean
  /** 大纲是否可编辑（确认 / 草稿 / 重新生成仅 owner 或有 project:write 权限） */
  canEditOutline: (isOwner: boolean) => boolean
  /** 章节是否可编制：项目 owner 或章节（含任一子节）assignee */
  canEditChapter: (assigneeIds: Array<string | null | undefined>, isOwner: boolean) => boolean
  /** 是否可以审核章节（通过/打回）：项目 owner */
  canReviewChapter: (isOwner: boolean) => boolean
  /** 是否可以管理项目成员：项目 owner */
  canManageMembers: (isOwner: boolean) => boolean
  /** 是否可以删除项目：项目 owner 或有 project:delete 权限 */
  canDeleteProject: (isOwner: boolean) => boolean
  /** 是否可以上传资料：有 kb:write 权限 */
  canUploadMaterial: () => boolean
  /** 是否可以编辑/删除资料：kb_admin 或资料上传者本人 */
  canEditMaterial: (uploaderId?: string | null) => boolean
}

export function usePermission(): UsePermissionReturn {
  const userId = computed(() => currentUserId.value)
  const role = computed(() => currentRole.value)

  /** 合并后端权限点 + 角色默认权限点 */
  const allPermissions = computed(() => {
    const rolePerms = ROLE_PERMISSIONS[currentRole.value] || []
    return new Set([...rolePerms, ...currentPermissions.value])
  })

  const can = (code: string): boolean => allPermissions.value.has(code)

  const isProjectOwner = (projectOwnerId?: string | null): boolean =>
    !!projectOwnerId && !!currentUserId.value && projectOwnerId === currentUserId.value

  const canEditOutline = (isOwner: boolean): boolean => isOwner || can('project:write')

  const canEditChapter = (
    assigneeIds: Array<string | null | undefined>,
    isOwner: boolean,
  ): boolean =>
    isOwner || assigneeIds.some((id) => !!id && id === currentUserId.value)

  const canReviewChapter = (isOwner: boolean): boolean => isOwner

  const canManageMembers = (isOwner: boolean): boolean => isOwner

  const canDeleteProject = (isOwner: boolean): boolean => isOwner || can('project:delete')

  const canUploadMaterial = (): boolean => can('kb:write')

  const canEditMaterial = (uploaderId?: string | null): boolean =>
    isKbAdminStore.value || (!!uploaderId && uploaderId === currentUserId.value)

  return {
    currentUserId: userId,
    currentRole: role,
    isAdmin: isAdminStore,
    isKbAdmin: isKbAdminStore,
    can,
    isProjectOwner,
    canEditOutline,
    canEditChapter,
    canReviewChapter,
    canManageMembers,
    canDeleteProject,
    canUploadMaterial,
    canEditMaterial,
  }
}
