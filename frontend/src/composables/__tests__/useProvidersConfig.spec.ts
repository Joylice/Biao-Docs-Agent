/**
 * useProvidersConfig 逻辑测试（T02，mock API 依赖注入，无真实请求）.
 *
 * 重点覆盖三态 payload 构造矩阵（最高回归风险点）：
 * - 未改动 → 不发请求（payload 不携带任何密钥字段）；
 * - 输入新 key → 携带新值；api_base 未触碰不携带；
 * - 显式"清除" → 携带空串（后端清空已存密钥）；
 * - 疑似脱敏串（sk-****xxxx）→ 前端拒传（抛错，不发请求）；
 * - custom 条目：llm_model/llm_api_base 变更才携带，必填全量字段透传；
 * - 测试连接成功（业务 ok）/ 业务失败（ok:false）/ 请求异常三分支。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（本 spec 经 deps 注入 mock API，不触网）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import {
  createProvidersConfig,
  isMaskedKey,
  type ProvidersConfigDeps,
} from '@/composables/useProvidersConfig'
import type { Provider } from '@/api/providers'
import type { ConnectionTestResult, LlmSettings } from '@/api/settings'

/* ---------------- fixtures ---------------- */

function mkProvider(prefix: string, over: Partial<Provider> = {}): Provider {
  return {
    id: `id-${prefix}`,
    name: prefix,
    prefix,
    apiKeyMasked: 'sk-****abcd',
    configured: true,
    apiBase: '',
    defaultBase: 'https://api.example.com/v1',
    capabilities: { text: true, embedding: false, rerank: false, vision: false },
    builtin: true,
    enabled: true,
    models: [],
    ...over,
  }
}

function mkSettings(over: Partial<LlmSettings> = {}): LlmSettings {
  return {
    deepseek_api_key: 'sk-****dsds',
    dashscope_api_key: '',
    openai_api_key: '',
    anthropic_api_key: '',
    zhipu_api_key: '',
    moonshot_api_key: '',
    llm_model: 'qwen72b',
    llm_api_base: 'http://123.249.37.244:7778/v1',
    llm_api_key: 'sk-****cust',
    embedding_api_base: 'http://emb:11434/v1',
    embedding_model: 'bge-m3',
    embedding_api_key: '',
    llm_mock: false,
    deepseek_configured: true,
    dashscope_configured: false,
    openai_configured: false,
    anthropic_configured: false,
    zhipu_configured: false,
    moonshot_configured: false,
    llm_key_configured: true,
    embedding_configured: false,
    ...over,
  }
}

function mkProviders(): Provider[] {
  return [
    mkProvider('deepseek', { apiBase: '', defaultBase: 'https://api.deepseek.com/v1' }),
    mkProvider('zhipu', { configured: false, apiKeyMasked: '' }),
    mkProvider('custom', { builtin: false }),
    mkProvider('openai'), // 白名单外：数据层保留，composable 不消费
  ]
}

function setup(over: Partial<ProvidersConfigDeps> = {}) {
  const deps: ProvidersConfigDeps = {
    getProviders: vi.fn().mockResolvedValue(mkProviders()),
    getLlmSettings: vi.fn().mockResolvedValue(mkSettings()),
    updateProvider: vi.fn().mockResolvedValue({}),
    updateLlmSettings: vi.fn().mockResolvedValue(undefined),
    testConnection: vi.fn().mockResolvedValue({ ok: true, latency_ms: 128 } as ConnectionTestResult),
    notifyError: vi.fn(),
    ...over,
  }
  const config = createProvidersConfig(deps)
  return { config, ...deps }
}

const loadOk = async (over: Partial<ProvidersConfigDeps> = {}) => {
  const ctx = setup(over)
  await ctx.config.load()
  return ctx
}

beforeEach(() => {
  vi.clearAllMocks()
})

/* ---------------- load ---------------- */

describe('load', () => {
  it('按 prefix 填充条目 provider 视图（custom/deepseek/zhipu），白名单外不消费', async () => {
    const { config, notifyError } = await loadOk()

    expect(config.entries['llm:deepseek'].provider?.id).toBe('id-deepseek')
    expect(config.entries['llm:zhipu'].provider?.id).toBe('id-zhipu')
    expect(config.entries['llm:custom'].provider?.id).toBe('id-custom')
    expect(config.providers.value.some((p) => p.prefix === 'openai')).toBe(true) // 数据在，条目不消费
    expect(config.customGlobal.llmModel).toBe('qwen72b')
    expect(notifyError).not.toHaveBeenCalled()
  })

  it('加载失败：notifyError 透出，不抛出', async () => {
    const { config, notifyError } = setup({
      getProviders: vi.fn().mockRejectedValue(new Error('boom')),
    })

    await expect(config.load()).resolves.toBeUndefined()
    expect(notifyError).toHaveBeenCalled()
  })
})

/* ---------------- 三态 payload 矩阵（云端提供方） ---------------- */

describe('saveProvider 三态矩阵', () => {
  it('未改动：不发请求（updateProvider 未调用）', async () => {
    const { config, updateProvider } = await loadOk()

    await config.saveProvider('llm:deepseek')

    expect(updateProvider).not.toHaveBeenCalled()
  })

  it('输入新 key：payload 仅携带 api_key（api_base 未触碰不携带）', async () => {
    const { config, updateProvider } = await loadOk()

    config.entries['llm:deepseek'].form.keyInput = 'sk-new-real-key'
    await config.saveProvider('llm:deepseek')

    expect(updateProvider).toHaveBeenCalledWith('id-deepseek', { api_key: 'sk-new-real-key' })
  })

  it('显式清除：payload.api_key 为空串（清空已存密钥）', async () => {
    const { config, updateProvider } = await loadOk()

    config.clearKey('llm:deepseek')
    expect(config.isDirtyProvider('llm:deepseek')).toBe(true)
    await config.saveProvider('llm:deepseek')

    expect(updateProvider).toHaveBeenCalledWith('id-deepseek', { api_key: '' })
  })

  it('掩码串拒传：抛错且不发请求（S-1 前端对齐）', async () => {
    const { config, updateProvider } = await loadOk()

    config.entries['llm:deepseek'].form.keyInput = 'sk-****abcd'
    await expect(config.saveProvider('llm:deepseek')).rejects.toThrow('疑似脱敏串')
    expect(updateProvider).not.toHaveBeenCalled()
  })

  it('改 api_base：触碰后携带（含空串=清除自定义端点）；未触碰不携带', async () => {
    const { config, updateProvider } = await loadOk()

    // 未触碰：即使值与原值一致也不携带
    await config.saveProvider('llm:deepseek')
    expect(updateProvider).not.toHaveBeenCalled()

    // 触碰且变化：携带新地址
    config.entries['llm:deepseek'].form.apiBase = 'https://mirror.example.com/v1'
    config.entries['llm:deepseek'].form.apiBaseTouched = true
    await config.saveProvider('llm:deepseek')
    expect(updateProvider).toHaveBeenCalledWith('id-deepseek', {
      api_base: 'https://mirror.example.com/v1',
    })

    // 触碰且清空：携带空串（清除）——上次保存已 reload 重置触碰标记，需重新触碰
    config.entries['llm:deepseek'].form.apiBaseTouched = true
    config.entries['llm:deepseek'].form.apiBase = ''
    await config.saveProvider('llm:deepseek')
    expect(updateProvider).toHaveBeenLastCalledWith('id-deepseek', { api_base: '' })
  })

  it('key + api_base 同时修改：payload 同时携带（一次请求）', async () => {
    const { config, updateProvider } = await loadOk()

    config.entries['llm:zhipu'].form.keyInput = 'sk-zp-new'
    config.entries['llm:zhipu'].form.apiBase = 'https://zp-mirror/v1'
    config.entries['llm:zhipu'].form.apiBaseTouched = true
    await config.saveProvider('llm:zhipu')

    expect(updateProvider).toHaveBeenCalledWith('id-zhipu', {
      api_key: 'sk-zp-new',
      api_base: 'https://zp-mirror/v1',
    })
  })

  it('保存成功后 reload（掩码刷新、表单重置回未改动态）', async () => {
    const { config, updateProvider } = await loadOk()

    config.entries['llm:deepseek'].form.keyInput = 'sk-new-real-key'
    await config.saveProvider('llm:deepseek')

    expect(updateProvider).toHaveBeenCalledTimes(1)
    expect(config.entries['llm:deepseek'].form.keyInput).toBe('') // 已重置
    expect(config.isDirtyProvider('llm:deepseek')).toBe(false)
  })

  it('条目 provider 缺失：抛错（store 保留脏状态）', async () => {
    const { config } = await loadOk({
      getProviders: vi.fn().mockResolvedValue([mkProvider('deepseek')]),
    })

    // zhipu 行不存在
    await expect(config.saveProvider('llm:zhipu')).rejects.toThrow('未找到对应服务商')
  })
})

/* ---------------- custom 条目 ---------------- */

describe('saveCustom 三态', () => {
  it('未改动：不发请求', async () => {
    const { config, updateLlmSettings } = await loadOk()

    await config.saveCustom()

    expect(updateLlmSettings).not.toHaveBeenCalled()
  })

  it('改主模型：payload 携带 llm_model + 必填全量透传字段', async () => {
    const { config, updateLlmSettings } = await loadOk()

    config.customGlobal.llmModel = 'qwen72b-v2'
    await config.saveCustom()

    expect(updateLlmSettings).toHaveBeenCalledWith({
      embedding_api_base: 'http://emb:11434/v1',
      embedding_model: 'bge-m3',
      llm_mock: false,
      llm_model: 'qwen72b-v2',
    })
  })

  it('新端点密钥：payload 携带 llm_api_key（后端 R1 写 providers custom 行）', async () => {
    const { config, updateLlmSettings } = await loadOk()

    config.entries['llm:custom'].form.keyInput = 'sk-custom-new'
    await config.saveCustom()

    expect(updateLlmSettings).toHaveBeenCalledWith(
      expect.objectContaining({ llm_api_key: 'sk-custom-new' }),
    )
  })

  it('清除端点密钥：payload.llm_api_key 为空串', async () => {
    const { config, updateLlmSettings } = await loadOk()

    config.clearKey('llm:custom')
    expect(config.isDirtyCustom()).toBe(true)
    await config.saveCustom()

    expect(updateLlmSettings).toHaveBeenCalledWith(
      expect.objectContaining({ llm_api_key: '' }),
    )
  })

  it('custom 掩码串拒传', async () => {
    const { config, updateLlmSettings } = await loadOk()

    config.entries['llm:custom'].form.keyInput = 'sk-****cust'
    await expect(config.saveCustom()).rejects.toThrow('疑似脱敏串')
    expect(updateLlmSettings).not.toHaveBeenCalled()
  })
})

/* ---------------- 先测后存门禁 ---------------- */

describe('saveCustom 连通性门禁', () => {
  it('连接字段有变更：先按表单值测试，通过后才保存', async () => {
    const { config, testConnection, updateLlmSettings } = await loadOk()

    config.customGlobal.llmModel = 'glm-5.2'
    config.customGlobal.llmApiBase = 'http://host.docker.internal:3100/v1'
    config.entries['llm:custom'].form.keyInput = 'sk-live'
    await config.saveCustom()

    expect(testConnection).toHaveBeenCalledWith('llm', {
      model: 'glm-5.2',
      api_base: 'http://host.docker.internal:3100/v1',
      api_key: 'sk-live',
    })
    expect(updateLlmSettings).toHaveBeenCalledWith(
      expect.objectContaining({ llm_model: 'glm-5.2' }),
    )
  })

  it('连通失败：中止保存（updateLlmSettings 不调用），错误含测试原因', async () => {
    const { config, updateLlmSettings } = await loadOk({
      testConnection: vi.fn().mockResolvedValue({ ok: false, error: '调用失败: Connection error' }),
    })

    config.customGlobal.llmApiBase = 'http://localhost:3100/v1'
    await expect(config.saveCustom()).rejects.toThrow('连通性测试未通过')
    expect(updateLlmSettings).not.toHaveBeenCalled()
  })

  it('仅清除密钥（连接变更）：同样先测后存', async () => {
    const { config, testConnection, updateLlmSettings } = await loadOk()

    config.clearKey('llm:custom')
    await config.saveCustom()

    expect(testConnection).toHaveBeenCalledWith(
      'llm',
      expect.objectContaining({ api_key: '' }),
    )
    expect(updateLlmSettings).toHaveBeenCalledWith(
      expect.objectContaining({ llm_api_key: '' }),
    )
  })
})

/* ---------------- 测试连接（P0-4） ---------------- */

describe('runTest', () => {
  it('业务成功：testResult.ok=true 且透出延迟', async () => {
    const { config, testConnection } = await loadOk()

    const result = await config.runTest()

    expect(testConnection).toHaveBeenCalledWith('llm', undefined)
    expect(result?.ok).toBe(true)
    expect(result?.latency_ms).toBe(128)
    expect(config.testing.value).toBe(false)
  })

  it('覆盖模式：overrides 透传给 testConnection（表单未保存值测试）', async () => {
    const { config, testConnection } = await loadOk()

    await config.runTest({ model: 'glm-5.2', api_base: 'http://host:3100/v1', api_key: 'sk-x' })

    expect(testConnection).toHaveBeenCalledWith('llm', {
      model: 'glm-5.2',
      api_base: 'http://host:3100/v1',
      api_key: 'sk-x',
    })
  })

  it('业务失败（HTTP 200 但 ok:false）：归一透出 error', async () => {
    const { config } = await loadOk({
      testConnection: vi.fn().mockResolvedValue({ ok: false, error: '调用失败: auth' }),
    })

    const result = await config.runTest()

    expect(result?.ok).toBe(false)
    expect(result?.error).toContain('auth')
  })

  it('请求异常：归一为 ok:false，不抛出', async () => {
    const { config } = await loadOk({
      testConnection: vi.fn().mockRejectedValue(new Error('network down')),
    })

    const result = await config.runTest()

    expect(result?.ok).toBe(false)
    expect(config.testing.value).toBe(false)
  })
})

/* ---------------- isMaskedKey ---------------- */

describe('isMaskedKey', () => {
  it('与后端 S-1 规则对齐：连续 4 星号判为疑似脱敏串', () => {
    expect(isMaskedKey('sk-****1234')).toBe(true)
    expect(isMaskedKey('****')).toBe(true)
    expect(isMaskedKey('abc_-****rest')).toBe(true)
    expect(isMaskedKey('sk-real-key-1234')).toBe(false)
    expect(isMaskedKey('')).toBe(false)
  })
})
