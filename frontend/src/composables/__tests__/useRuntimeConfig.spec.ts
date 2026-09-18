/**
 * useRuntimeConfig 逻辑测试（配置中心运行控制面板）.
 *
 * 覆盖：load 并行填充 mock/用量摘要/用量趋势；load 失败透出；
 * setMock 确认后透传 embedding 快照并提交 llm_mock；取消不请求；
 * 保存失败返回 false 且不回写 mockEnabled。
 * 审计日志已移出本面板 —— 断言 API 不再被调用。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('ant-design-vue', () => ({
  Modal: { confirm: vi.fn() },
  message: { success: vi.fn(), error: vi.fn() },
}))

// @/api/client 模块级 import @/router → @/stores/ui（window.localStorage），
// node 环境无 window：替身注入断开该链路（本 spec 经 deps 注入 mock API，不触网）
vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { createRuntimeConfig, type RuntimeConfigDeps } from '@/composables/useRuntimeConfig'
import type { LlmSettings } from '@/api/settings'
import type { AgentProfilesResponse, UsageSummary, UsageTrendResponse } from '@/api/usage'

function mkSettings(over: Partial<LlmSettings> = {}): LlmSettings {
  return {
    deepseek_api_key: '',
    dashscope_api_key: '',
    openai_api_key: '',
    anthropic_api_key: '',
    zhipu_api_key: '',
    moonshot_api_key: '',
    llm_model: 'deepseek/deepseek-chat',
    llm_api_base: '',
    llm_api_key: '',
    embedding_api_base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    embedding_model: 'dashscope/text-embedding-v3',
    embedding_api_key: '',
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

const mkUsage = (): UsageSummary => ({
  total_calls: 5,
  success_rate: 0.8,
  total_tokens: 30608,
  avg_latency_ms: 1200,
})

const mkTrend = (): UsageTrendResponse => ({
  days: 30,
  dates: ['2026-09-09', '2026-09-10'],
  dimension: 'agent',
  series: [
    {
      category: 'parse',
      label: '招标解析',
      calls: 3,
      ok_calls: 3,
      failed_calls: 0,
      total_tokens: 28154,
      points: [0, 28154],
      stages: [
        { stage_key: 'parse', label: '招标文件解析', calls: 2, ok_calls: 2, tokens: 25600 },
        { stage_key: 'score', label: '评分点解析', calls: 1, ok_calls: 1, tokens: 2554 },
      ],
      models: [{ model: 'deepseek/deepseek-chat', calls: 3, tokens: 28154 }],
    },
  ],
})

const mkProfiles = (): AgentProfilesResponse => ({
  days: 30,
  items: [
    {
      agent_id: 'score_agent',
      label: '评分点提取',
      calls: 4,
      ok_calls: 3,
      failed_calls: 1,
      success_rate: 0.75,
      avg_latency_ms: 812,
      total_tokens: 1234,
      tool_rows: 1,
      tool_calls_total: 2,
    },
  ],
})

function setup(over: Partial<RuntimeConfigDeps> = {}) {
  const deps: RuntimeConfigDeps = {
    getSettings: vi.fn().mockResolvedValue(mkSettings()),
    updateLlmSettings: vi.fn().mockResolvedValue({}),
    getUsage: vi.fn().mockResolvedValue(mkUsage()),
    getUsageTrend: vi.fn().mockResolvedValue(mkTrend()),
    getAgentProfiles: vi.fn().mockResolvedValue(mkProfiles()),
    confirmMock: vi.fn().mockResolvedValue(true),
    notifyError: vi.fn(),
    notifySuccess: vi.fn(),
    ...over,
  }
  const config = createRuntimeConfig(deps)
  return { config, ...deps }
}

describe('useRuntimeConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('load 并行填充 mock 开关 / 用量摘要 / 用量趋势 / 解析智能体画像', async () => {
    const { config, getUsage, getUsageTrend, getAgentProfiles } = setup({
      getSettings: vi.fn().mockResolvedValue(mkSettings({ llm_mock: true })),
    })

    await config.load()

    expect(config.mockEnabled.value).toBe(true)
    expect(config.usage.value?.total_calls).toBe(5)
    expect(config.usageTrend.value?.series[0].category).toBe('parse')
    expect(config.usageTrend.value?.series[0].label).toBe('招标解析')
    expect(getUsage).toHaveBeenCalledWith(30)
    expect(getUsageTrend).toHaveBeenCalledWith(30, 'agent')
    // ADR-0004 A2：画像与其它用量同批并行取，label 直接取后端值
    expect(config.agentProfiles.value?.items[0].label).toBe('评分点提取')
    expect(config.agentProfiles.value?.items[0].failed_calls).toBe(1)
    expect(getAgentProfiles).toHaveBeenCalledWith(30)
    expect(config.loading.value).toBe(false)
  })

  it('load 失败透出错误且不抛出', async () => {
    const { config, notifyError } = setup({
      getSettings: vi.fn().mockRejectedValue(new Error('boom')),
    })

    await config.load()

    expect(notifyError).toHaveBeenCalled()
    expect(config.loading.value).toBe(false)
  })

  it('setMock 确认后透传 embedding 快照并提交 llm_mock', async () => {
    const updateLlmSettings = vi.fn().mockResolvedValue({})
    const { config } = setup({ updateLlmSettings })

    await config.load()
    const ok = await config.setMock(true)

    expect(ok).toBe(true)
    expect(updateLlmSettings).toHaveBeenCalledWith({
      embedding_api_base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      embedding_model: 'dashscope/text-embedding-v3',
      llm_mock: true,
    })
    expect(config.mockEnabled.value).toBe(true)
  })

  it('setMock 取消时不发请求且返回 false', async () => {
    const updateLlmSettings = vi.fn()
    const { config } = setup({
      updateLlmSettings,
      confirmMock: vi.fn().mockResolvedValue(false),
    })

    await config.load()
    const ok = await config.setMock(true)

    expect(ok).toBe(false)
    expect(updateLlmSettings).not.toHaveBeenCalled()
    expect(config.mockEnabled.value).toBe(false)
  })

  it('setMock 保存失败返回 false 且不回写 mockEnabled', async () => {
    const { config, notifyError } = setup({
      updateLlmSettings: vi.fn().mockRejectedValue(new Error('500')),
    })

    await config.load()
    const ok = await config.setMock(true)

    expect(ok).toBe(false)
    expect(config.mockEnabled.value).toBe(false)
    expect(notifyError).toHaveBeenCalled()
  })

  it('面板不再暴露审计日志接口', () => {
    const { config } = setup()
    expect('auditLogs' in config).toBe(false)
    expect('loadAuditLogs' in config).toBe(false)
  })

  it('setTrendDimension 切换维度仅重取趋势数据', async () => {
    const { config, getUsageTrend } = setup()

    await config.load()
    vi.mocked(getUsageTrend).mockClear()
    await config.setTrendDimension('model')

    expect(config.trendDimension.value).toBe('model')
    expect(getUsageTrend).toHaveBeenCalledTimes(1)
    expect(getUsageTrend).toHaveBeenCalledWith(30, 'model')
  })

  it('setTrendDimension 同维度重复切换不发请求', async () => {
    const { config, getUsageTrend } = setup()

    await config.load()
    vi.mocked(getUsageTrend).mockClear()
    await config.setTrendDimension('agent')

    expect(getUsageTrend).not.toHaveBeenCalled()
  })
})
