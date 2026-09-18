/**
 * usageChart 纯几何/格式化函数测试（UsageTrendChart 绘制内核）.
 *
 * 组件用 SVG 直接渲染、项目未引入 @vue/test-utils，故把 x/y 映射、nice 刻度、
 * 路径拼接、悬浮索引反解外置为纯函数并在此锁定行为。
 */
import { describe, expect, it } from 'vitest'

import {
  buildLinePath,
  buildPoints,
  buildSeriesDetail,
  buildXTicks,
  buildYTicks,
  formatTokens,
  indexAtX,
  niceMax,
  plotHeight,
  plotWidth,
  shortDate,
  xAt,
  yAt,
  type ChartPadding,
} from '@/utils/usageChart'

const PADDING: ChartPadding = { top: 16, right: 16, bottom: 28, left: 52 }
const WIDTH = 720
const HEIGHT = 220

describe('niceMax', () => {
  it('峰值向上取整到 1/2/5 × 10^n 档位', () => {
    expect(niceMax([1])).toBe(1)
    expect(niceMax([1.5])).toBe(2)
    expect(niceMax([3])).toBe(5)
    expect(niceMax([7])).toBe(10)
    expect(niceMax([28154])).toBe(50_000)
    expect(niceMax([120])).toBe(200)
  })

  it('全零或空输入返回 1（避免除零）', () => {
    expect(niceMax([])).toBe(1)
    expect(niceMax([0, 0])).toBe(1)
  })

  it('忽略非法值', () => {
    expect(niceMax([Number.NaN, 0, 5])).toBe(5)
  })
})

describe('xAt / yAt 映射', () => {
  it('首点贴左内边距、末点贴右内边距', () => {
    const first = xAt(0, 5, WIDTH, PADDING)
    const last = xAt(4, 5, WIDTH, PADDING)

    expect(first).toBe(PADDING.left)
    expect(last).toBeCloseTo(WIDTH - PADDING.right, 5)
  })

  it('单点时居中', () => {
    expect(xAt(0, 1, WIDTH, PADDING)).toBeCloseTo(PADDING.left + plotWidth(WIDTH, PADDING) / 2, 5)
  })

  it('y=0 落底部、y=yMax 落顶部', () => {
    expect(yAt(0, 1000, HEIGHT, PADDING)).toBeCloseTo(
      PADDING.top + plotHeight(HEIGHT, PADDING),
      5,
    )
    expect(yAt(1000, 1000, HEIGHT, PADDING)).toBeCloseTo(PADDING.top, 5)
  })

  it('yMax 为 0 时不产生 NaN', () => {
    expect(Number.isFinite(yAt(0, 0, HEIGHT, PADDING))).toBe(true)
  })
})

describe('buildYTicks', () => {
  it('生成 5 条等分刻度，含 0 与上限', () => {
    const ticks = buildYTicks(1000, HEIGHT, PADDING)

    expect(ticks.map((t) => t.value)).toEqual([0, 250, 500, 750, 1000])
    // y 轴自下而上递减
    expect(ticks[0].y).toBeGreaterThan(ticks[4].y)
    expect(ticks[4].y).toBeCloseTo(PADDING.top, 5)
  })
})

describe('buildXTicks', () => {
  it('日期数少于阈值时全部展示', () => {
    const dates = ['2026-09-01', '2026-09-02', '2026-09-03']
    const ticks = buildXTicks(dates, WIDTH, PADDING, 6)

    expect(ticks).toHaveLength(3)
    expect(ticks[0].label).toBe('09-01')
  })

  it('日期数多时采样且末位必显', () => {
    const dates = Array.from({ length: 30 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`)
    const ticks = buildXTicks(dates, WIDTH, PADDING, 6)

    expect(ticks.length).toBeLessThanOrEqual(7)
    expect(ticks[ticks.length - 1].index).toBe(29)
    // 索引严格递增，x 同步递增
    for (let i = 1; i < ticks.length; i += 1) {
      expect(ticks[i].index).toBeGreaterThan(ticks[i - 1].index)
      expect(ticks[i].x).toBeGreaterThan(ticks[i - 1].x)
    }
  })

  it('空日期返回空数组', () => {
    expect(buildXTicks([], WIDTH, PADDING)).toEqual([])
  })
})

describe('buildLinePath / buildPoints', () => {
  it('首个指令为 M，其余为 L', () => {
    const path = buildLinePath([0, 100, 50], 3, 100, WIDTH, HEIGHT, PADDING)

    expect(path.startsWith('M')).toBe(true)
    expect(path.match(/L/g)).toHaveLength(2)
    expect(path).not.toContain('NaN')
  })

  it('空序列返回空字符串', () => {
    expect(buildLinePath([], 0, 100, WIDTH, HEIGHT, PADDING)).toBe('')
  })

  it('补零日（值 0）落在底部基准线', () => {
    const points = buildPoints([0], 3, 100, WIDTH, HEIGHT, PADDING)

    expect(points[0].y).toBeCloseTo(PADDING.top + plotHeight(HEIGHT, PADDING), 5)
  })
})

describe('indexAtX 悬浮反解', () => {
  it('落在左端返回 0、右端返回末位', () => {
    expect(indexAtX(PADDING.left, 5, WIDTH, PADDING)).toBe(0)
    expect(indexAtX(WIDTH - PADDING.right, 5, WIDTH, PADDING)).toBe(4)
  })

  it('超出绘图区时夹紧', () => {
    expect(indexAtX(-999, 5, WIDTH, PADDING)).toBe(0)
    expect(indexAtX(9999, 5, WIDTH, PADDING)).toBe(4)
  })

  it('单点恒返回 0', () => {
    expect(indexAtX(400, 1, WIDTH, PADDING)).toBe(0)
  })
})

describe('formatTokens / shortDate', () => {
  it('按 k/M 缩写', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(999)).toBe('999')
    expect(formatTokens(12_345)).toBe('12.3k')
    expect(formatTokens(1_500_000)).toBe('1.5M')
  })

  it('非数字输入退化为 0', () => {
    expect(formatTokens(Number.NaN)).toBe('0')
  })

  it('日期截断为 MM-DD，非标准格式原样返回', () => {
    expect(shortDate('2026-09-10')).toBe('09-10')
    expect(shortDate('bad')).toBe('bad')
  })
})

describe('buildSeriesDetail（图例悬浮下钻明细）', () => {
  it('依次给出阶段 / 模型 / 调用三行', () => {
    const lines = buildSeriesDetail({
      stages: [
        { label: '招标文件解析', tokens: 235_268 },
        { label: '评分点解析', tokens: 2_454 },
      ],
      models: [{ model: 'deepseek/deepseek-chat', tokens: 237_722, calls: 12 }],
      calls: 12,
      ok_calls: 10,
      failed_calls: 2,
    })

    expect(lines).toEqual([
      '阶段：招标文件解析 235.3k · 评分点解析 2.5k',
      '模型：deepseek/deepseek-chat 237.7k（12 次）',
      '调用：12 次，成功 10 次，失败 2 次',
    ])
  })

  it('多阶段类别合并后仍可下钻看清构成（招标解析 = parse + score）', () => {
    const lines = buildSeriesDetail({
      stages: [
        { label: '招标文件解析', tokens: 235_268 },
        { label: '评分点解析', tokens: 2_454 },
      ],
      calls: 12,
      ok_calls: 10,
      failed_calls: 2,
    })

    expect(lines[0]).toContain('招标文件解析')
    expect(lines[0]).toContain('评分点解析')
  })

  it('失败调用无 token 计量时仍报出失败次数（解释 token 为 0）', () => {
    const lines = buildSeriesDetail({
      stages: [
        { label: '章节撰写', tokens: 0 },
        { label: '校验复核', tokens: 0 },
        { label: '一致性检查', tokens: 0 },
      ],
      models: [{ model: 'openai/glm-4-plus', tokens: 0, calls: 72 }],
      calls: 72,
      ok_calls: 0,
      failed_calls: 72,
    })

    expect(lines).toContain('调用：72 次，成功 0 次，失败 72 次')
    expect(lines[0]).toBe('阶段：章节撰写 0 · 校验复核 0 · 一致性检查 0')
  })

  it('缺失 stages/models 时只给调用行，不产生空行', () => {
    const lines = buildSeriesDetail({ calls: 3, ok_calls: 3, failed_calls: 0 })

    expect(lines).toEqual(['调用：3 次，成功 3 次，失败 0 次'])
  })
})
