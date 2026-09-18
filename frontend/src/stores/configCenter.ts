/**
 * 配置中心弹窗状态（Pinia store，ARCH §1.4）.
 *
 * 职责：弹窗可见性、当前分类/条目、跨条目存活的脏状态集合、保存中条目、
 * 概览刷新版本号；入口权限校验、关闭二次确认、按条目粒度保存。
 *
 * 设计要点：
 * - 脏状态以条目 id 全局记录（Set），切换分类/条目不丢失提示（PRD 3.2），
 *   切换条目不弹确认，仅关闭弹窗时统一确认；
 * - 权限校验在 open() 内做（旧 /settings 路由守卫随路由删除而失效）；
 * - saveCurrent() 经 configRegistry 解析当前条目的 save 闭包，成功后
 *   clearDirty + bumpOverview（OverviewPanel watch 版本号重取汇总）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { hasPerm } from '@/stores/currentUser'
import {
  OVERVIEW_ITEM_ID,
  resolveEntry,
} from '@/config/configRegistry'

/** 弹窗入口权限点（与旧 /settings 路由 meta.perm 一致） */
export const CONFIG_CENTER_PERM = 'system:manage'

export const useConfigCenterStore = defineStore('configCenter', () => {
  /* ---------------- state ---------------- */
  const visible = ref(false)
  const activeCategoryId = ref<string>('overview')
  const activeItemId = ref<string | null>(OVERVIEW_ITEM_ID)
  /** 有未保存改动的条目 id 集合（跨分类/条目切换存活） */
  const dirtyItems = ref<Set<string>>(new Set())
  /** 正在保存的条目 id（null = 空闲；同一条目串行保存） */
  const savingId = ref<string | null>(null)
  /** 任一条目保存成功后 ++，OverviewPanel watch 它重取汇总数据 */
  const overviewVersion = ref(0)

  /* ---------------- actions ---------------- */

  /**
   * 打开弹窗。权限不足时拒绝并返回 false（调用方可不提示，静默忽略）；
   * itemId 合法时直接定位该条目，否则回退概览条目。
   */
  function open(itemId?: string): boolean {
    if (!hasPerm(CONFIG_CENTER_PERM)) {
      return false
    }
    const target = itemId ?? OVERVIEW_ITEM_ID
    const entry = resolveEntry(target)
    if (entry) {
      activeItemId.value = entry.id
      activeCategoryId.value = entry.categoryId
    } else {
      activeItemId.value = OVERVIEW_ITEM_ID
      activeCategoryId.value = 'overview'
    }
    visible.value = true
    return true
  }

  /** 切换条目（无需确认；脏状态不丢失，导航角标继续提示）。未知条目忽略。 */
  function selectItem(itemId: string): void {
    const entry = resolveEntry(itemId)
    if (!entry) return
    activeItemId.value = entry.id
    activeCategoryId.value = entry.categoryId
  }

  /** 标记条目有未保存改动（面板表单变更时调用） */
  function markDirty(itemId: string): void {
    dirtyItems.value.add(itemId)
  }

  /** 清除条目脏状态（保存成功后由 saveCurrent 调用） */
  function clearDirty(itemId: string): void {
    dirtyItems.value.delete(itemId)
  }

  /** 概览数据版本号 +1（保存成功后触发 OverviewPanel 重取） */
  function bumpOverview(): void {
    overviewVersion.value += 1
  }

  /**
   * 请求关闭弹窗：无未保存改动直接关；有则走确认弹窗（放弃改动/继续编辑），
   * 确认放弃时清空全部脏状态并关闭。Modal.confirm 挂 body，层级高于弹窗。
   */
  function requestClose(): void {
    if (dirtyItems.value.size === 0) {
      visible.value = false
      return
    }
    Modal.confirm({
      title: '有未保存的改动',
      content: '当前有配置项修改尚未保存，关闭后将丢弃这些改动。',
      okText: '放弃改动并关闭',
      okType: 'danger',
      cancelText: '继续编辑',
      onOk: () => {
        dirtyItems.value.clear()
        visible.value = false
      },
    })
  }

  /**
   * 保存当前条目：解析 registry 条目的 save 闭包并执行；成功后清除脏状态、
   * bump 概览版本并提示；失败保留脏状态并提示原因。同一时间仅允许一个保存。
   *
   * @returns 是否保存成功（无条目/已有保存进行中/保存失败均为 false）
   */
  async function saveCurrent(): Promise<boolean> {
    const itemId = activeItemId.value
    const entry = resolveEntry(itemId)
    if (!entry || savingId.value !== null) {
      return false
    }
    savingId.value = entry.id
    try {
      await entry.save()
      clearDirty(entry.id)
      bumpOverview()
      message.success('已保存')
      return true
    } catch (e) {
      const reason = e instanceof Error && e.message ? e.message : '保存失败，请稍后重试'
      message.error(reason)
      return false
    } finally {
      savingId.value = null
    }
  }

  return {
    visible,
    activeCategoryId,
    activeItemId,
    dirtyItems,
    savingId,
    overviewVersion,
    open,
    selectItem,
    markDirty,
    clearDirty,
    bumpOverview,
    requestClose,
    saveCurrent,
  }
})
