/**
 * 权限判定 composable（阶段 D：统一语义化权限入口）.
 *
 * 角色状态复用 stores/currentUser 模块级 ref（/auth/me 写入）；
 * 项目级判定由各页面拉取项目详情得到 owner_id 后传入比较。
 * 后端已做 403 兜底，此处仅控制前端入口可见性。
 */
import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import {
  currentUserId,
  isAdmin as isAdminStore,
  isKbAdmin as isKbAdminStore,
} from '@/stores/currentUser'

export interface UsePermissionReturn {
  /** 当前登录用户 ID */
  currentUserId: ComputedRef<string>
  /** 系统管理员（用户管理 / 审计日志 / 模型设置） */
  isAdmin: ComputedRef<boolean>
  /** 资料库管理员（全局资料删除 / 编辑，admin 天然包含） */
  isKbAdmin: ComputedRef<boolean>
  /** 当前用户是否为项目 owner（owner_id 与当前用户 ID 比较） */
  isProjectOwner: (projectOwnerId?: string | null) => boolean
  /** 大纲是否可编辑（确认 / 草稿 / 重新生成仅 owner） */
  canEditOutline: (isOwner: boolean) => boolean
  /** 章节是否可编制：项目 owner 或章节（含任一子节）assignee */
  canEditChapter: (assigneeIds: Array<string | null | undefined>, isOwner: boolean) => boolean
}

export function usePermission(): UsePermissionReturn {
  const userId = computed(() => currentUserId.value)

  const isProjectOwner = (projectOwnerId?: string | null): boolean =>
    !!projectOwnerId && !!currentUserId.value && projectOwnerId === currentUserId.value

  const canEditOutline = (isOwner: boolean): boolean => isOwner

  const canEditChapter = (
    assigneeIds: Array<string | null | undefined>,
    isOwner: boolean,
  ): boolean =>
    isOwner || assigneeIds.some((id) => !!id && id === currentUserId.value)

  return {
    currentUserId: userId,
    isAdmin: isAdminStore,
    isKbAdmin: isKbAdminStore,
    isProjectOwner,
    canEditOutline,
    canEditChapter,
  }
}
