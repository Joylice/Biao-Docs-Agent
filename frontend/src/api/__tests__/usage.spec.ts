/**
 * usage API 纯函数测试 — summarizeUsage 聚合口径.
 *
 * 背景：后端 /usage/summary 返回按 (stage_key, model) 分组的明细数组，
 * 历史实现按扁平字段读取导致面板成功率显示 NaN%。本 spec 锁定聚合口径。
 */
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import api from '@/api/client'
import {
  getAgentProfiles,
  hasNoToolTrace,
  summarizeUsage,
  type AgentProfileItem,
  type UsageSummaryItem,
} from '@/api/usage'

function mkItem(over: Partial<UsageSummaryItem> = {}): UsageSummaryItem {
  return {
    stage_key: 'write',
    category: 'write',
    category_label: '方案生成',
    model: 'deepseek/deepseek-chat',
    calls: 1,
    ok_calls: 1,
    success_rate: 1,
    total_tokens: 100,
    avg_latency_ms: 100,
    ...over,
  }
}

function mkProfile(over: Partial<AgentProfileItem> = {}): AgentProfileItem {
  return {
    agent_id: 'score_agent',
    label: '评分点提取',
    calls: 4,
    ok_calls: 3,
    failed_calls: 1,
    success_rate: 0.75,
    avg_latency_ms: 812,
    total_tokens: 1234,
    tool_rows: 0,
    tool_calls_total: 0,
    ...over,
  }
}

describe('getAgentProfiles', () => {
  it('请求 /usage/agent-profiles 并带天数参数', async () => {
    const items = [mkProfile()]
    vi.mocked(api.get).mockResolvedValue({ data: { code: 0, data: { days: 30, items } } })

    const res = await getAgentProfiles(30)

    expect(api.get).toHaveBeenCalledWith('/usage/agent-profiles', { params: { days: 30 } })
    expect(res?.items[0].label).toBe('评分点提取')
    // 前端直接消费后端 label，不自贴中文名
    expect(res?.items[0].label).not.toBe(res?.items[0].agent_id)
  })

  it('缺 data 时返回 null（不抛）', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { code: 0 } })
    expect(await getAgentProfiles(30)).toBeNull()
  })

  it('接口失败静默返回 null（不阻塞面板）', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500'))
    expect(await getAgentProfiles(30)).toBeNull()
  })
})

describe('hasNoToolTrace', () => {
  it('有数据但全无工具留痕 → true（提示工具默认关闭）', () => {
    expect(hasNoToolTrace([mkProfile(), mkProfile({ agent_id: 'norm_agent' })])).toBe(true)
  })

  it('任一行有工具留痕 → false', () => {
    expect(hasNoToolTrace([mkProfile({ tool_rows: 2 })])).toBe(false)
  })

  it('空列表 → false（走空状态而非该提示，避免误导）', () => {
    expect(hasNoToolTrace([])).toBe(false)
  })
})

describe('summarizeUsage', () => {
  it('多项求和：调用数 / 成功数 / token 总量', () => {
    const summary = summarizeUsage([
      mkItem({ calls: 4, ok_calls: 3, total_tokens: 1000, avg_latency_ms: 250 }),
      mkItem({ stage_key: 'parse', calls: 2, ok_calls: 2, total_tokens: 200, avg_latency_ms: 100 }),
    ])

    expect(summary.total_calls).toBe(6)
    expect(summary.success_rate).toBeCloseTo(5 / 6, 5)
    expect(summary.total_tokens).toBe(1200)
  })

  it('平均延迟按调用次数加权（非简单平均）', () => {
    const summary = summarizeUsage([
      mkItem({ calls: 3, ok_calls: 3, avg_latency_ms: 1000 }),
      mkItem({ calls: 1, ok_calls: 1, avg_latency_ms: 2000 }),
    ])

    // (1000*3 + 2000*1) / 4 = 1250
    expect(summary.avg_latency_ms).toBe(1250)
  })

  it('空明细返回全零且成功率不为 NaN', () => {
    const summary = summarizeUsage([])

    expect(summary.total_calls).toBe(0)
    expect(summary.success_rate).toBe(0)
    expect(summary.total_tokens).toBe(0)
    expect(summary.avg_latency_ms).toBe(0)
  })

  it('全失败调用成功率归零', () => {
    const summary = summarizeUsage([mkItem({ calls: 2, ok_calls: 0, success_rate: 0 })])

    expect(summary.total_calls).toBe(2)
    expect(summary.success_rate).toBe(0)
  })
})
