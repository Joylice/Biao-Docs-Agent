/**
 * useRetrievalConfig 逻辑测试（T03，mock API 依赖注入，无真实请求）.
 *
 * 覆盖：load 填充与失败透出 / localStorage 回退分支（api 层）/ 数值范围
 * 校验边界（P1-6）/ api_base URL 校验 / embedding+rerank 密钥三态 /
 * save 双端点提交与无改动直返 / reindex 确认流。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（数据侧全部依赖注入 mock，不触网）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { createRetrievalConfig, type RetrievalConfigDeps } from '@/composables/useRetrievalConfig'
import { getRetrievalParams } from '@/api/retrieval'
import type { LlmSettings } from '@/api/settings'
import type { RetrievalParamsDB } from '@/api/retrieval'

/* ---------------- fixtures ---------------- */

function mkSettings(over: Partial<LlmSettings> = {}): LlmSettings {
  return {
    deepseek_api_key: '',
    dashscope_api_key: '',
    openai_api_key: '',
    anthropic_api_key: '',
    zhipu_api_key: '',
    moonshot_api_key: '',
    llm_model: 'qwen72b',
    llm_api_base: '',
    llm_api_key: '',
    embedding_api_base: 'http://emb:11434/v1',
    embedding_model: 'bge-m3',
    embedding_api_key: 'sk-****embd',
    llm_mock: false,
    deepseek_configured: false,
    dashscope_configured: false,
    openai_configured: false,
    anthropic_configured: false,
    zhipu_configured: false,
    moonshot_configured: false,
    llm_key_configured: false,
    embedding_configured: true,
    ...over,
  }
}

function mkRetrieval(over: Partial<RetrievalParamsDB> = {}): RetrievalParamsDB {
  return {
    recall_top_k: 20,
    similarity_threshold: 0.35,
    hybrid_weight: 0.7,
    rerank_enabled: true,
    rerank_model: 'dashscope/gte-rerank',
    rerank_top_k: 5,
    rerank_api_key: 'sk-****rrnk',
    rerank_configured: true,
    ...over,
  }
}

function setup(over: Partial<RetrievalConfigDeps> = {}) {
  const deps: RetrievalConfigDeps = {
    getSettings: vi.fn().mockResolvedValue(mkSettings()),
    getRetrievalSettings: vi.fn().mockResolvedValue(mkRetrieval()),
    updateLlmSettings: vi.fn().mockResolvedValue(undefined),
    updateRetrievalParams: vi.fn().mockResolvedValue(undefined),
    testConnection: vi.fn().mockResolvedValue({ ok: true, dimension: 1024 }),
    reindex: vi.fn().mockResolvedValue({ enqueued: true, message: '索引重建任务已入队' }),
    confirmReindex: vi.fn().mockResolvedValue(true),
    notifyError: vi.fn(),
    notifySuccess: vi.fn(),
    ...over,
  }
  const config = createRetrievalConfig(deps)
  return { config, ...deps }
}

const loadOk = async (over: Partial<RetrievalConfigDeps> = {}) => {
  const ctx = setup(over)
  await ctx.config.load()
  return ctx
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/* ---------------- load ---------------- */

describe('load', () => {
  it('填充 embed/params/rerank 编辑态，密钥输入保持"保持"态', async () => {
    const { config } = await loadOk()

    expect(config.embed.model).toBe('bge-m3')
    expect(config.embed.apiBase).toBe('http://emb:11434/v1')
    expect(config.embed.configured).toBe(true)
    expect(config.embed.apiKeyMasked).toBe('sk-****embd')
    expect(config.embed.keyInput).toBe('')
    expect(config.embed.keyCleared).toBe(false)
    expect(config.params).toEqual({ recallTopK: 20, similarityThreshold: 0.35, hybridWeight: 0.7 })
    expect(config.rerank.enabled).toBe(true)
    expect(config.rerank.model).toBe('dashscope/gte-rerank')
    expect(config.rerank.topK).toBe(5)
    expect(config.isDirty()).toBe(false)
  })

  it('加载失败：notifyError 透出，不抛出', async () => {
    const { config, notifyError } = setup({
      getSettings: vi.fn().mockRejectedValue(new Error('boom')),
    })

    await expect(config.load()).resolves.toBeUndefined()
    expect(notifyError).toHaveBeenCalled()
  })
})

/* ---------------- localStorage 回退（api 层契约） ---------------- */

describe('api/retrieval getRetrievalParams 回退分支', () => {
  it('DB 失败 → 回退 localStorage 已存值', async () => {
    const store = {
      getItem: vi.fn().mockReturnValue(JSON.stringify({ recallTopK: 33, similarityThreshold: 0.5, hybridWeight: 0.2 })),
      setItem: vi.fn(),
    }
    vi.stubGlobal('localStorage', store)
    const client = (await import('@/api/client')).default as unknown as { get: ReturnType<typeof vi.fn> }
    client.get.mockRejectedValue(new Error('db down'))

    const params = await getRetrievalParams()

    expect(params).toEqual({ recallTopK: 33, similarityThreshold: 0.5, hybridWeight: 0.2 })
    expect(store.getItem).toHaveBeenCalledWith('bid-retrieval-params')
  })

  it('DB 失败且 localStorage 为空 → 默认值', async () => {
    vi.stubGlobal('localStorage', { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn() })
    const client = (await import('@/api/client')).default as unknown as { get: ReturnType<typeof vi.fn> }
    client.get.mockRejectedValue(new Error('db down'))

    const params = await getRetrievalParams()

    expect(params).toEqual({ recallTopK: 20, similarityThreshold: 0.35, hybridWeight: 0.7 })
  })
})

/* ---------------- P1-6 校验边界 ---------------- */

describe('validateAll 数值范围与 URL 校验', () => {
  it('recallTopK 边界：1/50 通过，0/51 拒绝；非整数拒绝', async () => {
    const { config, notifyError } = await loadOk()

    config.params.recallTopK = 1
    expect(config.validateAll()).toEqual([])
    config.params.recallTopK = 50
    expect(config.validateAll()).toEqual([])
    config.params.recallTopK = 0
    expect(config.validateAll().join()).toContain('召回 Top-K')
    config.params.recallTopK = 51
    expect(config.validateAll().join()).toContain('召回 Top-K')
    config.params.recallTopK = 2.5
    expect(config.validateAll().join()).toContain('整数')

    // 校验失败 → save 抛错且不发请求
    config.params.recallTopK = 0
    await expect(config.save()).rejects.toThrow()
    expect(notifyError).toHaveBeenCalled()
  })

  it('similarityThreshold/hybridWeight 边界：0/1 通过，越界拒绝', async () => {
    const { config } = await loadOk()

    config.params.similarityThreshold = 0
    config.params.hybridWeight = 1
    expect(config.validateAll()).toEqual([])
    config.params.similarityThreshold = -0.1
    expect(config.validateAll().join()).toContain('相似度阈值')
    config.params.hybridWeight = 1.1
    expect(config.validateAll().join()).toContain('混合检索权重')
  })

  it('rerank 停用时 topK 不校验；启用时越界拒绝', async () => {
    const { config } = await loadOk()

    config.rerank.enabled = false
    config.rerank.topK = 99
    expect(config.validateAll()).toEqual([])
    config.rerank.enabled = true
    expect(config.validateAll().join()).toContain('重排 Top-K')
    config.rerank.topK = 20
    expect(config.validateAll()).toEqual([])
  })

  it('api_base URL：合法 http(s)/空串通过，非法字符串与非 http 协议拒绝', async () => {
    const { config } = await loadOk()

    config.embed.apiBase = ''
    expect(config.validateAll()).toEqual([])
    config.embed.apiBase = 'http://emb:11434/v1'
    expect(config.validateAll()).toEqual([])
    config.embed.apiBase = 'https://emb.example.com/v1'
    expect(config.validateAll()).toEqual([])
    config.embed.apiBase = 'not-a-url'
    expect(config.validateAll().join()).toContain('Embedding 服务地址')
    config.embed.apiBase = 'ftp://emb:11434'
    expect(config.validateAll().join()).toContain('http/https')
  })
})

/* ---------------- 三态 payload（embedding + rerank 密钥） ---------------- */

describe('save 三态矩阵', () => {
  it('未改动：不发任何请求', async () => {
    const { config, updateLlmSettings, updateRetrievalParams } = await loadOk()

    await config.save()

    expect(updateLlmSettings).not.toHaveBeenCalled()
    expect(updateRetrievalParams).not.toHaveBeenCalled()
  })

  it('embedding 全量字段透传 + key 三态：留空省略/清除空串/新值携带', async () => {
    const { config, updateLlmSettings } = await loadOk()

    // 仅改模型：key 字段省略（保持原值）
    config.embed.model = 'bge-m3-v2'
    await config.save()
    expect(updateLlmSettings).toHaveBeenCalledWith({
      embedding_api_base: 'http://emb:11434/v1',
      embedding_model: 'bge-m3-v2',
      llm_mock: false,
    })

    // 显式清除：携带空串
    config.clearEmbedKey()
    await config.save()
    expect(updateLlmSettings).toHaveBeenLastCalledWith(
      expect.objectContaining({ embedding_api_key: '' }),
    )

    // 输入新值：携带新值
    await config.load()
    config.embed.keyInput = 'sk-emb-new'
    await config.save()
    expect(updateLlmSettings).toHaveBeenLastCalledWith(
      expect.objectContaining({ embedding_api_key: 'sk-emb-new' }),
    )
  })

  it('rerank key 三态 + 检索参数变更走 PUT /settings/retrieval', async () => {
    const { config, updateRetrievalParams } = await loadOk()

    config.params.recallTopK = 30
    config.rerank.enabled = false
    await config.save()
    expect(updateRetrievalParams).toHaveBeenCalledWith({
      recall_top_k: 30,
      rerank_enabled: false,
    })

    // 清除 rerank key
    await config.load()
    config.clearRerankKey()
    await config.save()
    expect(updateRetrievalParams).toHaveBeenLastCalledWith({ rerank_api_key: '' })

    // 新 rerank key
    await config.load()
    config.rerank.keyInput = 'sk-rr-new'
    await config.save()
    expect(updateRetrievalParams).toHaveBeenLastCalledWith({ rerank_api_key: 'sk-rr-new' })
  })

  it('掩码串拒传：embedding/rerank 均抛错且不发请求', async () => {
    const { config, updateLlmSettings, updateRetrievalParams } = await loadOk()

    config.embed.keyInput = 'sk-****embd'
    await expect(config.save()).rejects.toThrow('疑似脱敏串')
    expect(updateLlmSettings).not.toHaveBeenCalled()

    await config.load()
    config.rerank.keyInput = 'sk-****rrnk'
    await expect(config.save()).rejects.toThrow('疑似脱敏串')
    expect(updateRetrievalParams).not.toHaveBeenCalled()
  })

  it('保存成功后 reload，编辑态与脏标记重置', async () => {
    const { config, updateLlmSettings } = await loadOk()

    config.embed.model = 'bge-m3-v2'
    await config.save()

    expect(updateLlmSettings).toHaveBeenCalledTimes(1)
    expect(config.embed.model).toBe('bge-m3') // reload 后回到库内值（mock 固定）
    expect(config.isDirty()).toBe(false)
  })
})

/* ---------------- reindex 确认流 ---------------- */

describe('runReindex', () => {
  it('确认通过：调用 reindex 并 success 透出，返回 true', async () => {
    const { config, reindex, confirmReindex, notifySuccess } = await loadOk()

    const enqueued = await config.runReindex()

    expect(confirmReindex).toHaveBeenCalledTimes(1)
    expect(reindex).toHaveBeenCalledTimes(1)
    expect(enqueued).toBe(true)
    expect(notifySuccess).toHaveBeenCalledWith('索引重建任务已入队')
  })

  it('确认取消：不调用 reindex', async () => {
    const { config, reindex, confirmReindex } = await loadOk({
      confirmReindex: vi.fn().mockResolvedValue(false),
    })

    const enqueued = await config.runReindex()

    expect(confirmReindex).toHaveBeenCalledTimes(1)
    expect(reindex).not.toHaveBeenCalled()
    expect(enqueued).toBe(false)
  })

  it('入队失败（enqueued:false）：error 透出，返回 false；请求异常归一', async () => {
    const { config, notifyError } = await loadOk({
      reindex: vi.fn().mockResolvedValue({ enqueued: false, message: 'Redis 不可用' }),
    })
    expect(await config.runReindex()).toBe(false)
    expect(notifyError).toHaveBeenCalledWith('Redis 不可用')

    const ctx2 = await loadOk({ reindex: vi.fn().mockRejectedValue(new Error('boom')) })
    expect(await ctx2.config.runReindex()).toBe(false)
    expect(ctx2.notifyError).toHaveBeenCalled()
  })
})

/* ---------------- isDirty ---------------- */

describe('isDirty', () => {
  it('embed/params/rerank 任意改动置脏，load 后复位', async () => {
    const { config } = await loadOk()

    config.embed.model = 'x'
    expect(config.isDirtyEmbed()).toBe(true)
    expect(config.isDirty()).toBe(true)

    await config.load()
    config.params.recallTopK = 21
    expect(config.isDirty()).toBe(true)

    await config.load()
    config.rerank.model = 'other-rerank'
    expect(config.isDirty()).toBe(true)

    await config.load()
    config.clearRerankKey()
    expect(config.isDirty()).toBe(true)
  })
})
