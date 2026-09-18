/**
 * useExternalToolsConfig 逻辑测试（T04，mock API 依赖注入，无真实请求）.
 *
 * 覆盖：load 按 preset 填充 / 创建 vs 更新分流 / 乐观锁 expected_version 与
 * 409 冲突分支 / api_key 三态（留空省略、显式清除空串、新值、掩码拒传）/
 * 启停即时保存 / 删除确认流 / 绑定本地记录 / isDirtyPreset。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（数据侧全部依赖注入 mock，不触网）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import {
  createExternalToolsConfig,
  isConflictError,
  type ExternalToolsConfigDeps,
} from '@/composables/useExternalToolsConfig'
import type { ExternalTool } from '@/api/externalTools'

/* ---------------- fixtures ---------------- */

let versionSeq = 1

function mkTool(preset: string, over: Partial<ExternalTool> = {}): ExternalTool {
  return {
    id: `tool-${preset}`,
    name: `${preset} Search`,
    preset,
    toolType: 'http_search',
    apiKeyMasked: 'sk-****tool',
    configured: true,
    baseUrl: '',
    timeoutMs: 10000,
    maxQueryChars: 400,
    enabled: true,
    version: versionSeq++,
    ...over,
  }
}

function setup(over: Partial<ExternalToolsConfigDeps> = {}) {
  const deps: ExternalToolsConfigDeps = {
    // 动态生成：每次 load 返回新行（version 随 versionSeq 递增，模拟 DB 自增）
    getTools: vi.fn().mockImplementation(async () => [mkTool('tavily')]),
    createTool: vi.fn().mockImplementation(async () => mkTool('brave')),
    updateTool: vi.fn().mockImplementation((_id: string, payload: { expected_version: number; enabled?: boolean }) =>
      Promise.resolve(
        mkTool('tavily', {
          version: payload.expected_version + 1,
          ...(payload.enabled !== undefined ? { enabled: payload.enabled } : {}),
        }),
      ),
    ),
    deleteTool: vi.fn().mockResolvedValue(undefined),
    testTool: vi.fn().mockResolvedValue([{}]),
    bindTool: vi.fn().mockResolvedValue({}),
    unbindTool: vi.fn().mockResolvedValue(undefined),
    confirmDelete: vi.fn().mockResolvedValue(true),
    notifyError: vi.fn(),
    notifySuccess: vi.fn(),
    ...over,
  }
  const config = createExternalToolsConfig(deps)
  return { config, ...deps }
}

const loadOk = async (over: Partial<ExternalToolsConfigDeps> = {}) => {
  const ctx = setup(over)
  await ctx.config.load()
  return ctx
}

beforeEach(() => {
  vi.clearAllMocks()
  versionSeq = 1
})

/* ---------------- load ---------------- */

describe('load', () => {
  it('按 preset 填充表单（有行 fills 快照/version，无行保持 fresh）', async () => {
    const { config } = await loadOk()

    const tavily = config.forms.tavily
    expect(tavily.exists).toBe(true)
    expect(tavily.name).toBe('tavily Search')
    expect(tavily.rowId).toBe('tool-tavily')
    expect(tavily.configured).toBe(true)
    expect(tavily.snapshot).not.toBeNull()
    expect(config.isDirtyPreset('tavily')).toBe(false)

    // brave/searxng 无行：fresh 表单
    expect(config.forms.brave.exists).toBe(false)
    expect(config.forms.searxng.exists).toBe(false)
    expect(config.isDirtyPreset('brave')).toBe(false)
  })

  it('加载失败：notifyError 透出，不抛出', async () => {
    const { config, notifyError } = setup({ getTools: vi.fn().mockRejectedValue(new Error('boom')) })

    await expect(config.load()).resolves.toBeUndefined()
    expect(notifyError).toHaveBeenCalled()
  })
})

/* ---------------- 创建 vs 更新分流 + 三态 ---------------- */

describe('savePreset 分流与三态', () => {
  it('有行 → PUT 更新并携带 expected_version；未改 key 不携带 api_key', async () => {
    const { config, updateTool, createTool } = await loadOk()

    config.forms.tavily.name = 'Tavily 主搜索'
    await config.savePreset('tavily')

    expect(createTool).not.toHaveBeenCalled()
    expect(updateTool).toHaveBeenCalledWith(
      'tool-tavily',
      expect.objectContaining({ name: 'Tavily 主搜索', expected_version: 1 }),
    )
    expect(vi.mocked(updateTool).mock.calls[0][1]).not.toHaveProperty('api_key')
  })

  it('无行 → POST 创建并携带 preset', async () => {
    const { config, createTool, updateTool } = await loadOk()

    config.forms.brave.keyInput = 'sk-brave-new'
    await config.savePreset('brave')

    expect(updateTool).not.toHaveBeenCalled()
    expect(createTool).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Brave Search', preset: 'brave', api_key: 'sk-brave-new' }),
    )
  })

  it('三态：留空省略 / 显式清除空串 / 新值携带 / 掩码拒传', async () => {
    const { config, updateTool } = await loadOk()

    // 新值
    config.forms.tavily.keyInput = 'sk-tv-new'
    await config.savePreset('tavily')
    expect(updateTool).toHaveBeenLastCalledWith(
      'tool-tavily',
      expect.objectContaining({ api_key: 'sk-tv-new' }),
    )

    // 留空（省略）
    await config.load()
    config.forms.tavily.name = 'x1'
    await config.savePreset('tavily')
    expect(vi.mocked(updateTool).mock.lastCall![1]).not.toHaveProperty('api_key')

    // 显式清除
    await config.load()
    config.clearKey('tavily')
    await config.savePreset('tavily')
    expect(vi.mocked(updateTool).mock.lastCall![1]).toHaveProperty('api_key', '')

    // 掩码拒传
    await config.load()
    config.forms.tavily.keyInput = 'sk-****tool'
    await expect(config.savePreset('tavily')).rejects.toThrow('疑似脱敏串')
  })

  it('409 乐观锁冲突：抛"已被他人修改"', async () => {
    const conflict = Object.assign(new Error('conflict'), { response: { status: 409 } })
    const { config } = await loadOk({
      updateTool: vi.fn().mockRejectedValue(conflict),
    })

    config.forms.tavily.name = 'x'
    await expect(config.savePreset('tavily')).rejects.toThrow('已被他人修改')
  })

  it('保存成功后版本号推进（连续保存不再 409）', async () => {
    const { config, updateTool } = await loadOk()

    const firstVersion = config.forms.tavily.version
    config.forms.tavily.name = 'v2'
    await config.savePreset('tavily')

    // update 携带旧版本号；reload（GET 为准）后版本推进，连续保存不会再 409
    expect(vi.mocked(updateTool).mock.calls[0][1].expected_version).toBe(firstVersion)
    expect(config.forms.tavily.version).toBeGreaterThan(firstVersion)
  })

  it('isDirtyPreset：无行时任何非默认输入即脏；有行比较快照', async () => {
    const { config } = await loadOk()

    config.forms.searxng.baseUrl = 'http://sx:8080'
    expect(config.isDirtyPreset('searxng')).toBe(true)

    await config.load()
    config.forms.tavily.timeoutMs = 20000
    expect(config.isDirtyPreset('tavily')).toBe(true)
  })
})

/* ---------------- 启停 / 删除 / 测试 / 绑定 ---------------- */

describe('toggleEnable / remove / runTest / bind', () => {
  it('启停即时保存：携带 expected_version，成功本地同步', async () => {
    const { config, updateTool } = await loadOk()

    const tool = config.getToolByPreset('tavily')!
    const ok = await config.toggleEnable(tool, false)

    expect(ok).toBe(true)
    expect(updateTool).toHaveBeenCalledWith('tool-tavily', { enabled: false, expected_version: 1 })
    expect(tool.enabled).toBe(false)
  })

  it('确认通过 → 删除并 reload；取消 → 不调用', async () => {
    const { config, deleteTool } = await loadOk()

    expect(await config.remove('tavily')).toBe(true)
    expect(deleteTool).toHaveBeenCalledWith('tool-tavily')

    const ctx2 = await loadOk({ confirmDelete: vi.fn().mockResolvedValue(false) })
    expect(await ctx2.config.remove('tavily')).toBe(false)
    expect(ctx2.deleteTool).not.toHaveBeenCalled()
  })

  it('测试：结果首项含 error → 失败透出；无行 → 提示先保存', async () => {
    const { config, notifyError } = await loadOk({ testTool: vi.fn().mockResolvedValue([{ error: 'timeout' }]) })

    expect(await config.runTest('tavily')).toBe(false)
    expect(notifyError).toHaveBeenCalledWith(expect.stringContaining('timeout'))

    expect(await config.runTest('brave')).toBe(false) // 无行
    expect(notifyError).toHaveBeenCalledWith('尚未创建该工具，请先保存')
  })

  it('bind/unbind：调用端点并本地记录 bindings', async () => {
    const { config, bindTool, unbindTool } = await loadOk()

    const tool = config.getToolByPreset('tavily')!
    await config.bindStage(tool, 'parse')
    expect(bindTool).toHaveBeenCalledWith('tool-tavily', { stage_key: 'parse' })
    expect(config.bindings.value['tool-tavily']).toEqual(['parse'])

    await config.unbindStage(tool, 'parse')
    expect(unbindTool).toHaveBeenCalledWith('tool-tavily', 'parse')
    expect(config.bindings.value['tool-tavily']).toEqual([])
  })

  it('load 用后端 boundStages 初始化 bindings（首屏即可见已绑关系）', async () => {
    const { config } = await loadOk({
      getTools: vi.fn().mockResolvedValue([mkTool('tavily', { boundStages: ['outline', 'write'] })]),
    })

    expect(config.bindings.value['tool-tavily']).toEqual(['outline', 'write'])
  })

  it('bindNode/unbindNode：展开为编制节点组内全部 stage_key（仅一次成功通知）', async () => {
    const { config, bindTool, unbindTool, notifySuccess } = await loadOk()

    const tool = config.getToolByPreset('tavily')!
    // 方案生成 = write + validate + consistency
    await config.bindNode(tool, 'generate')
    expect(bindTool).toHaveBeenCalledTimes(3)
    expect(bindTool).toHaveBeenCalledWith('tool-tavily', { stage_key: 'write' })
    expect(bindTool).toHaveBeenCalledWith('tool-tavily', { stage_key: 'validate' })
    expect(bindTool).toHaveBeenCalledWith('tool-tavily', { stage_key: 'consistency' })
    expect(config.bindings.value['tool-tavily']).toEqual(['write', 'validate', 'consistency'])
    expect(notifySuccess).toHaveBeenCalledTimes(1)
    expect(notifySuccess).toHaveBeenCalledWith('已绑定到「方案生成」')

    await config.unbindNode(tool, 'generate')
    expect(unbindTool).toHaveBeenCalledTimes(3)
    expect(config.bindings.value['tool-tavily']).toEqual([])

    // 未知节点：直接 false，不触网
    expect(await config.bindNode(tool, 'nope')).toBe(false)
  })

  it('bindNode：「方案导出」不可绑定（无模型调用点，绑定即假绑定）', async () => {
    const { config, bindTool } = await loadOk()

    const tool = config.getToolByPreset('tavily')!
    expect(await config.bindNode(tool, 'export')).toBe(false)
    expect(bindTool).not.toHaveBeenCalled()
  })

  it('unbindNode：仍可解绑存量「方案导出」绑定（保留假绑定清理通道）', async () => {
    const { config, unbindTool } = await loadOk({
      getTools: vi.fn().mockResolvedValue([mkTool('tavily', { boundStages: ['export'] })]),
    })

    const tool = config.getToolByPreset('tavily')!
    expect(await config.unbindNode(tool, 'export')).toBe(true)
    expect(unbindTool).toHaveBeenCalledWith('tool-tavily', 'export')
    expect(config.bindings.value['tool-tavily']).toEqual([])
  })
})

/* ---------------- isConflictError ---------------- */

describe('isConflictError', () => {
  it('按 response.status === 409 判定', () => {
    expect(isConflictError(Object.assign(new Error('x'), { response: { status: 409 } }))).toBe(true)
    expect(isConflictError(Object.assign(new Error('x'), { response: { status: 500 } }))).toBe(false)
    expect(isConflictError(new Error('x'))).toBe(false)
    expect(isConflictError(null)).toBe(false)
  })
})
