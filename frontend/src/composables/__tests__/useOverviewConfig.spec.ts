/**
 * useOverviewConfig / useSkillsConfig 纯函数映射测试（T04）.
 *
 * buildOverviewSnapshot：白名单口径（custom/deepseek/zhipu + tavily/brave/
 * searxng）数据映射、缺行回退；阶段路由按 5 个投标编制节点归并
 * （8 个 stage_key → 5 节点，归并口径见 @/config/stageNodes）。
 * buildToolRows：工具→绑定阶段 + 关联编制节点映射。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { buildOverviewSnapshot } from '@/composables/useOverviewConfig'
import { buildToolRows, type ToolRow } from '@/composables/useSkillsConfig'
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

    // routes → 归并为 5 个投标编制节点（本用例仅提供 parse 一行）
    expect(snapshot.routeNodes).toHaveLength(5)
    expect(snapshot.routeNodes.map((n) => [n.index, n.label])).toEqual([
      [1, '招标解析'],
      [2, '方案大纲生成'],
      [3, '方案生成'],
      [4, '方案评审'],
      [5, '方案导出'],
    ])
    expect(snapshot.routeNodes[0]).toEqual({
      key: 'parse',
      index: 1,
      label: '招标解析',
      stageKeys: ['parse', 'score'],
      model: 'deepseek/deepseek-chat',
      stageCount: 1,
      disabledCount: 0,
    })
    // 缺行节点：stageCount=0、模型空（展示回退全局）、无停用标记
    expect(snapshot.routeNodes[4]).toEqual({
      key: 'export',
      index: 5,
      label: '方案导出',
      stageKeys: ['export'],
      model: '',
      stageCount: 0,
      disabledCount: 0,
    })
    // 归并口径：方案生成 = write + validate + consistency
    expect(snapshot.routeNodes[2].stageKeys).toEqual(['write', 'validate', 'consistency'])

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

  it('8 阶段归并为 5 节点：节点级模型取组内首条非空，停用按组计数', () => {
    const mk = (stageKey: string, model: string, enabled = true): ModelRoute => ({
      id: `route-${stageKey}`,
      stageKey,
      stageName: `阶段-${stageKey}`,
      nodeName: `node_${stageKey}`,
      model,
      fallback: [],
      thinking: false,
      temperature: 0.7,
      maxTokens: 4096,
      timeout: 120,
      hint: '',
      enabled,
    })

    const snapshot = buildOverviewSnapshot({
      providers: [],
      routes: [
        mk('parse', 'openai/glm-5.2'),
        mk('score', 'openai/glm-5.2'),
        mk('outline', ''),
        mk('write', 'openai/glm-5.2'),
        mk('validate', '', false),
        mk('consistency', '', false),
        mk('review', 'deepseek/deepseek-chat'),
        mk('export', 'deepseek/deepseek-chat'),
      ],
      llm: { embedding_model: '', embedding_configured: false },
      retrieval: { rerank_enabled: false, rerank_configured: false },
      tools: [],
    })

    // 归并覆盖：8 行全部落位到 5 个节点
    expect(snapshot.routeNodes).toHaveLength(5)
    expect(snapshot.routeNodes.reduce((n, x) => n + x.stageCount, 0)).toBe(8)

    // ① 招标解析：parse + score，模型取组内首条非空
    expect(snapshot.routeNodes[0]).toMatchObject({
      label: '招标解析',
      model: 'openai/glm-5.2',
      stageCount: 2,
      disabledCount: 0,
    })
    // ② 方案大纲生成：仅 outline，整组模型为空 → 展示回退全局
    expect(snapshot.routeNodes[1]).toMatchObject({
      label: '方案大纲生成',
      model: '',
      stageCount: 1,
      disabledCount: 0,
    })
    // ③ 方案生成：write + validate + consistency，2 项停用 → 部分停用
    expect(snapshot.routeNodes[2]).toMatchObject({
      label: '方案生成',
      model: 'openai/glm-5.2',
      stageCount: 3,
      disabledCount: 2,
    })
    // ⑤ 方案导出
    expect(snapshot.routeNodes[4]).toMatchObject({
      label: '方案导出',
      model: 'deepseek/deepseek-chat',
      stageCount: 1,
    })
  })
})

describe('buildToolRows', () => {
  it('工具 → 绑定阶段 + 关联编制节点映射', () => {
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
    const tool = (id: string, name: string, enabled = true): ExternalTool => ({
      id,
      name,
      preset: 'tavily',
      toolType: 'http_search',
      apiKeyMasked: '',
      configured: true,
      baseUrl: '',
      timeoutMs: 10000,
      maxQueryChars: 400,
      enabled,
      version: 1,
    })

    const rows = buildToolRows(
      [route('parse', '招标解析', true), route('write', '方案生成', false)],
      [tool('t1', 'Tavily 主搜索'), tool('t2', 'Brave 备用', false)],
      { t1: ['parse', 'write'], t2: ['parse'] },
    )

    expect(rows).toEqual<ToolRow[]>([
      {
        toolId: 't1',
        toolName: 'Tavily 主搜索',
        toolEnabled: true,
        nodeKeys: ['parse', 'generate'],
        nodeLabels: ['招标解析', '方案生成'],
        boundStages: [
          { stageKey: 'parse', stageName: '招标解析', stageEnabled: true },
          { stageKey: 'write', stageName: '方案生成', stageEnabled: false },
        ],
      },
      {
        toolId: 't2',
        toolName: 'Brave 备用',
        toolEnabled: false,
        nodeKeys: ['parse'],
        nodeLabels: ['招标解析'],
        boundStages: [{ stageKey: 'parse', stageName: '招标解析', stageEnabled: true }],
      },
    ])
  })

  it('绑定引用不存在的 stage_key 时静默剔除，且不产生空节点', () => {
    const route = (stageKey: string): ModelRoute => ({
      id: `route-${stageKey}`,
      stageKey,
      stageName: stageKey,
      nodeName: `node_${stageKey}`,
      model: 'm',
      fallback: [],
      thinking: false,
      temperature: 0.7,
      maxTokens: 4096,
      timeout: 120,
      hint: '',
      enabled: true,
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

    const rows = buildToolRows(
      [route('parse'), route('write')],
      [tool('t1', 'X')],
      { t1: ['parse', 'ghost'] }, // ghost 不在 routes 中
    )

    expect(rows).toEqual<ToolRow[]>([
      {
        toolId: 't1',
        toolName: 'X',
        toolEnabled: true,
        nodeKeys: ['parse'],
        nodeLabels: ['招标解析'],
        boundStages: [{ stageKey: 'parse', stageName: 'parse', stageEnabled: true }],
      },
    ])
  })
})
