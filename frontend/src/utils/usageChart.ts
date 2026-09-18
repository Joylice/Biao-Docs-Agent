/**
 * 用量趋势折线图的纯几何/格式化计算（UsageTrendChart 的绘制内核）.
 *
 * 抽成纯函数的原因：SVG 几何与刻度算法无法在 node 测试环境里靠挂载组件覆盖
 * （项目未引入 @vue/test-utils），外置后可单测 x/y 映射、nice 刻度、路径拼接。
 * 组件只负责把结果填进 <svg>，不含计算逻辑。
 */

/** 图表内边距（与组件保持一致，仅作默认值） */
export interface ChartPadding {
  top: number
  right: number
  bottom: number
  left: number
}

/** 坐标点 */
export interface Point {
  x: number
  y: number
}

/** y 轴刻度 */
export interface YTick {
  value: number
  y: number
}

/** x 轴刻度 */
export interface XTick {
  index: number
  x: number
  label: string
}

/**
 * y 轴上限取「好看」整数：1/2/5 × 10^n 中首个 ≥ 峰值的档位。
 * 全零或空输入返回 1，避免除零。
 */
export function niceMax(values: number[]): number {
  const raw = values.reduce((max, value) => Math.max(max, Number(value) || 0), 0)
  if (raw <= 0) return 1
  const exp = Math.floor(Math.log10(raw))
  const base = 10 ** exp
  const norm = raw / base
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  return step * base
}

/** 绘图区宽度 */
export function plotWidth(width: number, padding: ChartPadding): number {
  return Math.max(1, width - padding.left - padding.right)
}

/** 绘图区高度 */
export function plotHeight(height: number, padding: ChartPadding): number {
  return Math.max(1, height - padding.top - padding.bottom)
}

/** 第 index 个数据点的 x 坐标（单点时居中） */
export function xAt(index: number, count: number, width: number, padding: ChartPadding): number {
  const innerWidth = plotWidth(width, padding)
  if (count <= 1) return padding.left + innerWidth / 2
  return padding.left + (index / (count - 1)) * innerWidth
}

/** 数值 value 对应的 y 坐标（0 在底部，yMax 在顶部） */
export function yAt(value: number, yMax: number, height: number, padding: ChartPadding): number {
  const innerHeight = plotHeight(height, padding)
  const ratio = yMax ? (Number(value) || 0) / yMax : 0
  return padding.top + innerHeight - ratio * innerHeight
}

/** 等分 4 段生成 5 条水平刻度（含 0 与 yMax） */
export function buildYTicks(yMax: number, height: number, padding: ChartPadding): YTick[] {
  return [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    value: Math.round(yMax * ratio),
    y: yAt(yMax * ratio, yMax, height, padding),
  }))
}

/**
 * x 轴日期刻度：点数超过 maxLabels 时等间隔采样，并保证首尾必显。
 */
export function buildXTicks(
  dates: string[],
  width: number,
  padding: ChartPadding,
  maxLabels = 6,
): XTick[] {
  const count = dates.length
  if (count === 0) return []

  const stride = Math.max(1, Math.ceil(count / maxLabels))
  const ticks: XTick[] = []
  for (let index = 0; index < count; index += stride) {
    ticks.push({ index, x: xAt(index, count, width, padding), label: shortDate(dates[index]) })
  }

  const lastIndex = count - 1
  if (ticks[ticks.length - 1].index !== lastIndex) {
    ticks.push({
      index: lastIndex,
      x: xAt(lastIndex, count, width, padding),
      label: shortDate(dates[lastIndex]),
    })
  }
  return ticks
}

/** 各数据点的坐标序列（供折线路径与悬浮点复用） */
export function buildPoints(
  values: number[],
  count: number,
  yMax: number,
  width: number,
  height: number,
  padding: ChartPadding,
): Point[] {
  return values.map((value, index) => ({
    x: xAt(index, count, width, padding),
    y: yAt(value, yMax, height, padding),
  }))
}

/** 折线路径 d 指令（M/L 连接，保留 1 位小数） */
export function buildLinePath(
  values: number[],
  count: number,
  yMax: number,
  width: number,
  height: number,
  padding: ChartPadding,
): string {
  if (values.length === 0) return ''
  return buildPoints(values, count, yMax, width, height, padding)
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(' ')
}

/** 2026-09-10 → 09-10（非标准日期原样返回） */
export function shortDate(iso: string): string {
  const parts = String(iso).split('-')
  return parts.length >= 3 ? `${parts[1]}-${parts[2]}` : String(iso)
}

/** 12345 → 12.3k；1234567 → 1.2M（轴标签与图例复用） */
export function formatTokens(value: number): string {
  const n = Number(value) || 0
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

/** 按鼠标 x 反解最近的日期索引（超界夹紧） */
export function indexAtX(
  x: number,
  count: number,
  width: number,
  padding: ChartPadding,
): number {
  if (count <= 1) return 0
  const innerWidth = plotWidth(width, padding)
  const ratio = (x - padding.left) / innerWidth
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))))
}

/** 图例下钻明细的输入结构（结构化，避免 utils 反向依赖 api 层类型） */
export interface SeriesDetailInput {
  stages?: { label: string; tokens: number }[]
  models?: { model: string; tokens: number; calls: number }[]
  calls: number
  ok_calls: number
  failed_calls: number
}

/**
 * 组装图例悬浮明细行（阶段构成 → 模型构成 → 调用统计）.
 *
 * 一个智能体类别可能由多个流水线阶段合并而来（如「招标解析」= 招标文件解析 + 评分点解析），
 * 合并后必须能下钻看清内部构成，否则反而丢失信息。
 * 失败调用无 token 计量，故单独列出失败次数以解释「有调用但 token 为 0」。
 */
export function buildSeriesDetail(serie: SeriesDetailInput): string[] {
  const lines: string[] = []
  const stages = serie.stages ?? []
  if (stages.length > 0) {
    lines.push(`阶段：${stages.map((s) => `${s.label} ${formatTokens(s.tokens)}`).join(' · ')}`)
  }
  const models = serie.models ?? []
  if (models.length > 0) {
    lines.push(
      `模型：${models.map((m) => `${m.model} ${formatTokens(m.tokens)}（${m.calls} 次）`).join(' · ')}`,
    )
  }
  lines.push(`调用：${serie.calls} 次，成功 ${serie.ok_calls} 次，失败 ${serie.failed_calls} 次`)
  return lines
}
