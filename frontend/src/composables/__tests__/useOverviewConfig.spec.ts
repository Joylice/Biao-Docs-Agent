/**
 * useOverviewConfig / useSkillsConfig 纯函数映射测试（T04）.
 *
 * buildOverviewSnapshot：白名单口径（custom/deepseek/zhipu + tavily/brave/
 * searxng）数据映射、缺行回退。buildSkillRows：阶段→绑定工具映射。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { buildOverviewSnapshot } from '@/composables/useOverviewConfig'
import { buildSkillRows } from '@/composables/useSkillsConfig'
import type { ModelRoute } from '@/api/providers'
import type { ExternalTool } from '@/api/externalTools'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('buildOverviewSnapshot', () => {
  it('白名单口径映射，缺行回退默认态', () => {
    const snapshot = buildOverviewSnapshot({
      providers: [{ prefix: 'deepseek', configured: true, apiKeyMasked: 'sk-****dsds' }],
      routes: [
        {
          id: 'r1',
          stageKey: 'parse',
          stageName: '招标解析',
          nodeName: 'node_parse',
          model: 'deepseek/deepseek-chat',
          fallback: [],
          thinking: false,
          temperature: 0.7,
          maxTokens: 4096,
          timeout: 120,
          hint: '',
          enabled: true,
        },
      ],
      llm: { embedding_model: 'bge-m3', embedding_configured: true },
      retrieval: { rerank_enabled: true, rerank_configured: true },
      tools: [
        {
          id: 't1',
          name: 'Tavily 主搜索',
          preset: 'tavily',
          toolType: 'http_search',
          apiKeyMasked: 'sk-****tv',
          configured: true,
          baseUrl: '',
          timeoutMs: 10000,
          maxQueryChars: 400,
          enabled: true,
          version: 1,
        },
      ],
    })

    // providers：仅白名单 3 项；deepseek 有行，custom/zhipu 缺行回退
    expect(snapshot.providers).toHaveLength(3)
    const ds = snapshot.providers.find((p) => p.preset === 'deepseek')!
    expect(ds.configured).toBe(true)
    expect(ds.apiKeyMasked).toBe('sk-****dsds')
    expect(ds.lastTestOk).toBeNull()
    const zhipu = snapshot.providers.find((p) => p.preset === 'zhipu')!
    expect(zhipu.configured).toBe(false)
    expect(zhipu.apiKeyMasked).toBe('')

    // routes
    expect(snapshot.routes).toEqual([
      { stageKey: 'parse', stageName: '招标解析', model: 'deepseek/deepseek-chat', enabled: true },
    ])

    // retrieval
    expect(snapshot.retrieval).toEqual({
      embeddingModel: 'bge-m3',
      embeddingConfigured: true,
      rerankEnabled: true,
      rerankConfigured: true,
    })

    // tools：tavily 有行，brave/searxng 缺行回退
    expect(snapshot.tools).toHaveLength(3)
    expect(snapshot.tools[0]).toEqual({
      preset: 'tavily',
      name: 'Tavily 主搜索',
      configured: true,
      enabled: true,
      exists: true,
    })
    expect(snapshot.tools[1]).toEqual({
      preset: 'brave',
      name: 'Brave Search',
      configured: false,
      enabled: false,
      exists: false,
    })
  })
})

describe('buildSkillRows', () => {
  it('阶段 → 绑定工具名映射', () => {
    const route = (stageKey: string, stageName: string, enabled: boolean): ModelRoute => ({
      id: `route-${stageKey}`,
      stageKey,
      stageName,
      nodeName: `node_${stageKey}`,
      model: 'm',
      fallback: [],
      thinking: false,
      temperature: 0.7,
      maxTokens: 4096,
      timeout: 120,
      hint: '',
      enabled,
    })
    const tool = (id: string, name: string): ExternalTool => ({
      id,
      name,
      preset: 'tavily',
      toolType: 'http_search',
      apiKeyMasked: '',
      configured: true,
      baseUrl: '',
      timeoutMs: 10000,
      maxQueryChars: 400,
      enabled: true,
      version: 1,
    })

    const rows = buildSkillRows(
      [route('parse', '招标解析', true), route('write', '方案生成', false)],
      [tool('t1', 'Tavily 主搜索'), tool('t2', 'Brave 备用')],
      { t1: ['parse', 'write'], t2: ['parse'] },
    )

    expect(rows).toEqual([
      { stageKey: 'parse', stageName: '招标解析', enabled: true, boundToolNames: ['Tavily 主搜索', 'Brave 备用'] },
      { stageKey: 'write', stageName: '方案生成', enabled: false, boundToolNames: ['Tavily 主搜索'] },
    ])
  })
})
