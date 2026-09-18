/**
 * configCenterStore + configRegistry 单测（T01 基础设施回归）.
 *
 * 覆盖：open 权限校验与默认概览 / selectItem 流转 / markDirty-clearDirty /
 * requestClose 无脏直关 + 有脏 Modal.confirm 确认流 / saveCurrent 成功·失败·
 * 串行保护 / registry 结构与语言模型 UI 白名单（openai/anthropic/kimi/
 * dashscope 不注册）。
 *
 * 环境说明：vitest node 环境（无 DOM），ant-design-vue 的 Modal/message 以
 * vi.mock 替身注入，不触发真实渲染；registry 的占位面板为纯 HTML SFC。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('ant-design-vue', () => ({
  Modal: { confirm: vi.fn() },
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（store 单测只用到 hasPerm 等纯函数）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { Modal } from 'ant-design-vue'
import { setCurrentPermissions } from '@/stores/currentUser'
import { useConfigCenterStore } from '@/stores/configCenter'
import {
  LLM_UI_WHITELIST,
  OVERVIEW_ITEM_ID,
  findCategoryOfEntry,
  getConfigCategories,
  getEntriesByCategory,
  resolveEntry,
} from '@/config/configRegistry'

const confirmMock = vi.mocked(Modal.confirm)

const grantPerm = () => setCurrentPermissions(['system:manage'])
const revokePerm = () => setCurrentPermissions([])

const setupStore = () => useConfigCenterStore()

beforeEach(() => {
  setActivePinia(createPinia())
  confirmMock.mockClear()
  revokePerm()
})

afterEach(() => {
  // 恢复被个别用例替换的 registry save 闭包（占位 no-op）
  const entry = resolveEntry(OVERVIEW_ITEM_ID)
  if (entry) entry.save = async () => {}
})

describe('configCenterStore.open', () => {
  it('无权限：拒绝打开（visible 保持 false，返回 false）', () => {
    const store = setupStore()

    const ok = store.open()

    expect(ok).toBe(false)
    expect(store.visible).toBe(false)
  })

  it('有权限：打开弹窗并默认选中概览条目', () => {
    grantPerm()
    const store = setupStore()

    const ok = store.open()

    expect(ok).toBe(true)
    expect(store.visible).toBe(true)
    expect(store.activeItemId).toBe(OVERVIEW_ITEM_ID)
    expect(store.activeCategoryId).toBe('overview')
  })

  it('open(itemId)：合法条目直接定位（含分类联动）', () => {
    grantPerm()
    const store = setupStore()

    store.open('llm:deepseek')

    expect(store.visible).toBe(true)
    expect(store.activeItemId).toBe('llm:deepseek')
    expect(store.activeCategoryId).toBe('llm')
  })

  it('open(itemId)：未注册条目回退概览（不隐藏路由/书签类入口炸裂）', () => {
    grantPerm()
    const store = setupStore()

    store.open('llm:openai')

    expect(store.visible).toBe(true)
    expect(store.activeItemId).toBe(OVERVIEW_ITEM_ID)
    expect(store.activeCategoryId).toBe('overview')
  })
})

describe('configCenterStore.selectItem', () => {
  it('已知条目：更新 activeItemId 与 activeCategoryId', () => {
    grantPerm()
    const store = setupStore()
    store.open()

    store.selectItem('retrieval:params')

    expect(store.activeItemId).toBe('retrieval:params')
    expect(store.activeCategoryId).toBe('retrieval')
  })

  it('未知条目：忽略（active 不变）', () => {
    grantPerm()
    const store = setupStore()
    store.open()

    store.selectItem('llm:kimi')

    expect(store.activeItemId).toBe(OVERVIEW_ITEM_ID)
  })
})

describe('configCenterStore.dirty 流转', () => {
  it('markDirty/clearDirty：按条目 id 增删，跨条目互不影响', () => {
    const store = setupStore()

    store.markDirty('llm:deepseek')
    store.markDirty('retrieval:params')
    expect(store.dirtyItems.has('llm:deepseek')).toBe(true)
    expect(store.dirtyItems.has('retrieval:params')).toBe(true)

    store.clearDirty('llm:deepseek')
    expect(store.dirtyItems.has('llm:deepseek')).toBe(false)
    expect(store.dirtyItems.has('retrieval:params')).toBe(true)
  })

  it('无脏状态 requestClose：直接关闭，不弹确认', () => {
    grantPerm()
    const store = setupStore()
    store.open()

    store.requestClose()

    expect(store.visible).toBe(false)
    expect(confirmMock).not.toHaveBeenCalled()
  })

  it('有脏状态 requestClose：弹确认；确认放弃 → 清空脏状态并关闭', () => {
    grantPerm()
    const store = setupStore()
    store.open()
    store.markDirty('llm:deepseek')
    store.markDirty('retrieval:params')

    store.requestClose()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(store.visible).toBe(true) // 确认前保持打开

    const opts = confirmMock.mock.calls[0][0] as { onOk: () => void }
    opts.onOk()

    expect(store.dirtyItems.size).toBe(0)
    expect(store.visible).toBe(false)
  })

  it('有脏状态 requestClose：取消（不触发 onOk）→ 弹窗保持打开、脏状态保留', () => {
    grantPerm()
    const store = setupStore()
    store.open()
    store.markDirty('llm:deepseek')

    store.requestClose()
    // 未调用 onOk = 用户点了"继续编辑"

    expect(store.visible).toBe(true)
    expect(store.dirtyItems.has('llm:deepseek')).toBe(true)
  })
})

describe('configCenterStore.saveCurrent', () => {
  it('保存成功：清脏 + bumpOverview + success 提示', async () => {
    grantPerm()
    const store = setupStore()
    store.open()
    store.markDirty(OVERVIEW_ITEM_ID)
    const versionBefore = store.overviewVersion

    const ok = await store.saveCurrent()

    expect(ok).toBe(true)
    expect(store.dirtyItems.has(OVERVIEW_ITEM_ID)).toBe(false)
    expect(store.overviewVersion).toBe(versionBefore + 1)
    expect(store.savingId).toBeNull()
    const { message } = (await import('ant-design-vue')) as typeof import('ant-design-vue')
    expect(vi.mocked(message.success)).toHaveBeenCalledWith('已保存')
  })

  it('保存失败：保留脏状态 + error 提示 + savingId 复位', async () => {
    grantPerm()
    const store = setupStore()
    store.open()
    store.markDirty(OVERVIEW_ITEM_ID)
    const entry = resolveEntry(OVERVIEW_ITEM_ID)
    expect(entry).toBeDefined()
    entry!.save = async () => {
      throw new Error('网络异常')
    }

    const ok = await store.saveCurrent()

    expect(ok).toBe(false)
    expect(store.dirtyItems.has(OVERVIEW_ITEM_ID)).toBe(true)
    expect(store.savingId).toBeNull()
    const { message } = (await import('ant-design-vue')) as typeof import('ant-design-vue')
    expect(vi.mocked(message.error)).toHaveBeenCalledWith('网络异常')
  })

  it('串行保护：保存进行中再次 saveCurrent 返回 false，不重复触发', async () => {
    grantPerm()
    const store = setupStore()
    store.open()

    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const entry = resolveEntry(OVERVIEW_ITEM_ID)
    expect(entry).toBeDefined()
    entry!.save = async () => {
      await gate
    }

    const first = store.saveCurrent()
    const second = await store.saveCurrent()

    expect(second).toBe(false)
    expect(store.savingId).toBe(OVERVIEW_ITEM_ID)
    release()
    await expect(first).resolves.toBe(true)
    expect(store.savingId).toBeNull()
  })
})

describe('configCenterStore.bumpOverview', () => {
  it('每次 +1（OverviewPanel watch 驱动）', () => {
    const store = setupStore()
    const before = store.overviewVersion

    store.bumpOverview()
    store.bumpOverview()

    expect(store.overviewVersion).toBe(before + 2)
  })
})

describe('configRegistry 结构与白名单', () => {
  it('一级分类为 6 项且 id 与 ARCH 定稿一致', () => {
    const ids = getConfigCategories().map((c) => c.id)

    expect(ids).toEqual(['overview', 'llm', 'retrieval', 'websearch', 'skills', 'system'])
  })

  it('语言模型分类条目严格等于 UI 白名单', () => {
    const ids = getEntriesByCategory('llm').map((e) => e.id)

    expect(ids).toEqual([...LLM_UI_WHITELIST])
  })

  it('openai/anthropic/kimi/dashscope 不注册（数据层保留、UI 隐藏）', () => {
    for (const hidden of ['llm:openai', 'llm:anthropic', 'llm:kimi', 'llm:dashscope']) {
      expect(resolveEntry(hidden)).toBeUndefined()
      expect(findCategoryOfEntry(hidden)).toBeNull()
    }
  })

  it('每个分类至少挂 1 个条目，且条目 categoryId 均可回指分类', () => {
    const categories = getConfigCategories()

    for (const cat of categories) {
      const items = getEntriesByCategory(cat.id)
      expect(items.length).toBeGreaterThan(0)
      for (const item of items) {
        expect(item.categoryId).toBe(cat.id)
        expect(item.component).not.toBeNull()
        expect(typeof item.save).toBe('function')
        expect(typeof item.isDirty).toBe('function')
      }
    }
  })

  it('每个条目 id 唯一且形如 <分类>:<条目>', () => {
    const all = getConfigCategories().flatMap((c) => getEntriesByCategory(c.id))
    const ids = all.map((e) => e.id)

    expect(new Set(ids).size).toBe(ids.length)
    for (const e of all) {
      expect(e.id.startsWith(`${e.categoryId}:`)).toBe(true)
    }
  })
})
