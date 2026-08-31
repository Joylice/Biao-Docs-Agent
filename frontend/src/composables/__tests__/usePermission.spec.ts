/**
 * usePermission 权限判定测试（纯逻辑，无 DOM）.
 *
 * 角色/权限点来自 stores/currentUser 模块级 ref，测试中直接改写后断言；
 * 用例间通过 beforeEach 重置，避免状态泄漏。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// stores/currentUser 依赖 api client（引用 window），单测环境 mock 掉
vi.mock('@/api/client', () => ({ default: {} }))

import { usePermission } from '@/composables/usePermission'
import {
  currentPermissions,
  currentRole,
  currentUserId,
} from '@/stores/currentUser'

const { setCurrentPermissions, setCurrentUser } = await import('@/stores/currentUser')

describe('usePermission', () => {
  beforeEach(() => {
    currentUserId.value = ''
    currentRole.value = 'member'
    currentPermissions.value = []
  })

  it('isProjectOwner 仅当 owner_id 与当前用户一致', () => {
    const { isProjectOwner } = usePermission()
    setCurrentUser('u1')
    expect(isProjectOwner('u1')).toBe(true)
    expect(isProjectOwner('u2')).toBe(false)
    expect(isProjectOwner(null)).toBe(false)
    expect(isProjectOwner('')).toBe(false)
  })

  it('canEditOutline：owner 或 project:write 权限点', () => {
    const { canEditOutline } = usePermission()
    expect(canEditOutline(true)).toBe(true)
    expect(canEditOutline(false)).toBe(false)
    setCurrentPermissions(['project:write'])
    expect(canEditOutline(false)).toBe(true)
    expect(canEditOutline(true)).toBe(true)
  })

  it('canEditChapter：owner 或本人为任意章节 assignee', () => {
    const { canEditChapter } = usePermission()
    setCurrentUser('u1')
    expect(canEditChapter(['u1'], false)).toBe(true)
    expect(canEditChapter(['u2', null], false)).toBe(false)
    expect(canEditChapter([], true)).toBe(true)
    expect(canEditChapter(['u2'], false)).toBe(false)
  })

  it('canReviewChapter / canManageMembers 仅 owner', () => {
    const { canReviewChapter, canManageMembers } = usePermission()
    expect(canReviewChapter(true)).toBe(true)
    expect(canReviewChapter(false)).toBe(false)
    expect(canManageMembers(true)).toBe(true)
    expect(canManageMembers(false)).toBe(false)
  })

  it('canDeleteProject：owner 或 project:delete 权限点', () => {
    const { canDeleteProject } = usePermission()
    expect(canDeleteProject(true)).toBe(true)
    expect(canDeleteProject(false)).toBe(false)
    setCurrentPermissions(['project:delete'])
    expect(canDeleteProject(false)).toBe(true)
  })

  it('canUploadMaterial 需要 kb:write 权限点', () => {
    const { canUploadMaterial } = usePermission()
    expect(canUploadMaterial()).toBe(false)
    setCurrentPermissions(['kb:write'])
    expect(canUploadMaterial()).toBe(true)
  })

  it('canEditMaterial：kb_admin 或资料上传者本人', () => {
    const { canEditMaterial } = usePermission()
    setCurrentUser('u1')
    expect(canEditMaterial('u1')).toBe(true)
    expect(canEditMaterial('u2')).toBe(false)
    currentRole.value = 'kb_admin'
    expect(canEditMaterial('u2')).toBe(true)
  })

  it('角色兜底映射：admin 天然具备全部权限点', () => {
    const { can } = usePermission()
    currentRole.value = 'admin'
    expect(can('system:manage')).toBe(true)
    expect(can('project:delete')).toBe(true)
    currentRole.value = 'member'
    expect(can('system:manage')).toBe(false)
  })

  it('后端权限点与角色映射并集生效', () => {
    const { can } = usePermission()
    setCurrentPermissions(['kb:write'])
    expect(can('kb:write')).toBe(true)
    expect(can('project:create')).toBe(true) // member 角色默认权限点
    expect(can('project:delete')).toBe(false)
  })
})
