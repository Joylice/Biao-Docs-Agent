/**
 * useRoutesConfig 逻辑测试（T02，mock API 依赖注入）.
 *
 * 覆盖：load 填充与失败透出 / touch 脏集合与 isDirty / save 仅提交触碰过的
 * 阶段（并发批量）且 payload 不携带未开放编辑字段 / 保存成功后 reload 清脏 /
 * 保存失败抛错且脏集合保留 / 无改动直接返回。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（本 spec 经 deps 注入 mock API，不触网）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { createRoutesConfig, type RoutesConfigDeps } from '@/composables/useRoutesConfig'
import type { ModelRoute } from '@/api/providers'

function mkRoute(stageKey: string, over: Partial<ModelRoute> = {}): ModelRoute {
  return {
    id: `route-${stageKey}`,
    stageKey,
    stageName: `阶段-${stageKey}`,
    nodeName: `node_${stageKey}`,
    model: 'deepseek/deepseek-chat',
    fallback: [],
    thinking: false,
    temperature: 0.7,
    maxTokens: 4096,
    timeout: 120,
    hint: '',
    enabled: true,
    ...over,
  }
}

function mkRoutes(): ModelRoute[] {
  return [
    mkRoute('parse'),
    mkRoute('score'),
    mkRoute('outline'),
    mkRoute('write'),
    mkRoute('validate'),
    mkRoute('consistency'),
    mkRoute('review'),
    mkRoute('export'),
  ]
}

function setup(over: Partial<RoutesConfigDeps> = {}) {
  const deps: RoutesConfigDeps = {
    getRoutes: vi.fn().mockResolvedValue(mkRoutes()),
    updateRoute: vi.fn().mockResolvedValue({}),
    notifyError: vi.fn(),
    ...over,
  }
  const config = createRoutesConfig(deps)
  return { config, ...deps }
}

const loadOk = async (over: Partial<RoutesConfigDeps> = {}) => {
  const ctx = setup(over)
  await ctx.config.load()
  return ctx
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('load', () => {
  it('填充 8 阶段路由并清空脏集合', async () => {
    const { config, notifyError } = await loadOk()

    expect(config.routes.value).toHaveLength(8)
    expect(config.isDirty.value).toBe(false)
    expect(notifyError).not.toHaveBeenCalled()
  })

  it('加载失败：notifyError 透出，不抛出', async () => {
    const { config, notifyError } = setup({ getRoutes: vi.fn().mockRejectedValue(new Error('boom')) })

    await expect(config.load()).resolves.toBeUndefined()
    expect(notifyError).toHaveBeenCalled()
  })
})

describe('touch / isDirty', () => {
  it('touch 标记阶段，重复标记幂等；load 后清空', async () => {
    const { config } = await loadOk()

    config.touch('write')
    config.touch('write')
    config.touch('parse')

    expect(config.isDirty.value).toBe(true)
    expect(config.changedStages.value.size).toBe(2)

    await config.load()
    expect(config.isDirty.value).toBe(false)
  })
})

describe('save', () => {
  it('仅提交触碰过的阶段，payload 只含开放编辑字段', async () => {
    const { config, updateRoute } = await loadOk()

    config.touch('write')
    config.routes.value.find((r) => r.stageKey === 'write')!.temperature = 0.3
    config.touch('parse')
    await config.save()

    expect(updateRoute).toHaveBeenCalledTimes(2)
    expect(updateRoute).toHaveBeenCalledWith('write', {
      model: 'deepseek/deepseek-chat',
      temperature: 0.3,
      max_tokens: 4096,
      timeout: 120,
    })
    expect(updateRoute).toHaveBeenCalledWith('parse', {
      model: 'deepseek/deepseek-chat',
      temperature: 0.7,
      max_tokens: 4096,
      timeout: 120,
    })
    // 未触碰阶段不提交
    expect(updateRoute).not.toHaveBeenCalledWith('review', expect.anything())
  })

  it('保存成功后 reload 并清空脏集合', async () => {
    const { config, getRoutes } = await loadOk()

    config.touch('write')
    await config.save()

    expect(getRoutes).toHaveBeenCalledTimes(2) // load + save 后 reload
    expect(config.isDirty.value).toBe(false)
  })

  it('保存失败：抛错且脏集合保留（store 保留脏状态）', async () => {
    const { config } = await loadOk({
      updateRoute: vi.fn().mockRejectedValue(new Error('db down')),
    })

    config.touch('write')
    await expect(config.save()).rejects.toThrow('保存阶段路由失败')
    expect(config.isDirty.value).toBe(true)
  })

  it('空参数（temperature=null）不携带该字段', async () => {
    const { config, updateRoute } = await loadOk()

    config.routes.value.find((r) => r.stageKey === 'write')!.temperature = null
    config.touch('write')
    await config.save()

    expect(updateRoute).toHaveBeenCalledWith('write', {
      model: 'deepseek/deepseek-chat',
      temperature: undefined,
      max_tokens: 4096,
      timeout: 120,
    })
  })

  it('无改动：save 直接返回，不发请求', async () => {
    const { config, updateRoute } = await loadOk()

    await config.save()

    expect(updateRoute).not.toHaveBeenCalled()
  })
})
