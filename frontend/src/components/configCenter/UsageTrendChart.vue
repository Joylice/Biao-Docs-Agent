<template>
  <div
    ref="wrapRef"
    class="usage-trend"
  >
    <div
      v-if="!hasData"
      class="usage-trend__empty"
    >
      <span>暂无用量数据</span>
      <span class="usage-trend__empty-hint">产生真实 LLM 调用后，此处按智能体展示 Token 消耗趋势</span>
    </div>

    <template v-else>
      <div class="usage-trend__legend">
        <div
          v-for="(serie, i) in series"
          :key="serie.category"
          class="usage-trend__legend-item"
        >
          <span
            class="usage-trend__legend-dot"
            :style="{ background: colorOf(i) }"
          />
          <span class="usage-trend__legend-name">{{ serie.label }}</span>
          <span class="usage-trend__legend-value">{{ formatTokens(serie.total_tokens) }}</span>
          <span
            v-if="serie.failed_calls > 0"
            class="usage-trend__legend-failed"
          >{{ serie.failed_calls }} 次失败</span>

          <!-- 悬浮下钻明细：子阶段构成 + 模型构成（多阶段类别须能看清内部） -->
          <div class="usage-trend__legend-detail">
            <div
              v-for="(line, k) in buildSeriesDetail(serie)"
              :key="k"
              class="usage-trend__legend-detail-line"
            >
              {{ line }}
            </div>
          </div>
        </div>
      </div>

      <div class="usage-trend__plot">
        <svg
          ref="svgRef"
          :width="width"
          :height="height"
          class="usage-trend__svg"
          @mousemove="onMove"
          @mouseleave="hoverIndex = null"
        >
          <!-- 水平网格 + y 轴刻度 -->
          <g>
            <template
              v-for="tick in yTicks"
              :key="`y-${tick.value}`"
            >
              <line
                :x1="PADDING.left"
                :x2="width - PADDING.right"
                :y1="tick.y"
                :y2="tick.y"
                class="usage-trend__grid"
              />
              <text
                :x="PADDING.left - 8"
                :y="tick.y + 4"
                class="usage-trend__axis-label"
                text-anchor="end"
              >
                {{ formatTokens(tick.value) }}
              </text>
            </template>
          </g>

          <!-- x 轴日期刻度 -->
          <g>
            <text
              v-for="tick in xTicks"
              :key="`x-${tick.index}`"
              :x="tick.x"
              :y="height - PADDING.bottom + 16"
              class="usage-trend__axis-label"
              text-anchor="middle"
            >
              {{ tick.label }}
            </text>
          </g>

          <!-- 折线 -->
          <g>
            <path
              v-for="(serie, i) in series"
              :key="`line-${serie.category}`"
              :d="linePath(serie.points)"
              class="usage-trend__line"
              :style="{ stroke: colorOf(i) }"
            />
          </g>

          <!-- 悬浮辅助线 + 高亮点 -->
          <g v-if="hoverIndex !== null">
            <line
              :x1="xPos(hoverIndex)"
              :x2="xPos(hoverIndex)"
              :y1="PADDING.top"
              :y2="height - PADDING.bottom"
              class="usage-trend__cursor"
            />
            <circle
              v-for="(serie, i) in series"
              :key="`dot-${serie.category}`"
              :cx="xPos(hoverIndex)"
              :cy="yPos(serie.points[hoverIndex] ?? 0)"
              r="3.5"
              :fill="colorOf(i)"
              class="usage-trend__dot"
            />
          </g>
        </svg>

        <!-- 悬浮提示 -->
        <div
          v-if="hoverIndex !== null"
          class="usage-trend__tooltip"
          :style="tooltipStyle"
        >
          <div class="usage-trend__tooltip-title">
            {{ dates[hoverIndex] }}
          </div>
          <div
            v-for="(serie, i) in series"
            :key="`tip-${serie.category}`"
            class="usage-trend__tooltip-row"
          >
            <span
              class="usage-trend__legend-dot"
              :style="{ background: colorOf(i) }"
            />
            <span class="usage-trend__tooltip-name">{{ serie.label }}</span>
            <span class="usage-trend__tooltip-value">{{ formatTokens(serie.points[hoverIndex] ?? 0) }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * UsageTrendChart：各智能体 Token 用量折线图（配置中心运行控制面板）.
 *
 * 纯 SVG 自绘，不引入图表库（保持前端依赖面不扩大）：
 * - 多系列折线，x 轴为日期、y 轴为 Token 数（nice 刻度）
 * - 系列按「智能体类别」由后端归并（一个类别可能含多个流水线阶段），
 *   故图例不会出现同名重复；每个图例项悬浮可下钻查看阶段/模型构成
 * - 失败调用（无 token 计量）以「N 次失败」角标呈现，解释「有调用但 token 为 0」
 * - ResizeObserver 跟随容器宽度，避免 SVG 缩放导致字体形变
 * - 颜色/文字走设计变量与固定色板，明暗主题均可读
 * - 几何计算全部委托 utils/usageChart（纯函数，可单测）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { UsageTrendSeries } from '@/api/usage'
import {
  buildLinePath,
  buildSeriesDetail,
  buildXTicks,
  buildYTicks,
  formatTokens,
  indexAtX,
  niceMax,
  xAt,
  yAt,
  type ChartPadding,
} from '@/utils/usageChart'

const props = withDefaults(
  defineProps<{
    /** ISO 日期序列（与各系列 points 等长） */
    dates: string[]
    /** 各智能体折线（后端已按智能体类别归并，label 为中文名） */
    series: UsageTrendSeries[]
    height?: number
  }>(),
  { height: 220 },
)

const PADDING: ChartPadding = { top: 16, right: 16, bottom: 28, left: 52 }

/** 系列色板（明暗主题下均可辨识） */
const PALETTE = [
  '#3b82f6',
  '#10b981',
  '#f59e0b',
  '#8b5cf6',
  '#ef4444',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
]

const height = computed(() => props.height)
const wrapRef = ref<HTMLElement | null>(null)
const svgRef = ref<SVGSVGElement | null>(null)
const width = ref(640)
const hoverIndex = ref<number | null>(null)

const hasData = computed(() => props.dates.length > 0 && props.series.length > 0)

const colorOf = (index: number) => PALETTE[index % PALETTE.length]

const yMax = computed(() => niceMax(props.series.flatMap((serie) => serie.points)))

const yTicks = computed(() => buildYTicks(yMax.value, height.value, PADDING))
const xTicks = computed(() => buildXTicks(props.dates, width.value, PADDING))

const xPos = (index: number) => xAt(index, props.dates.length, width.value, PADDING)
const yPos = (value: number) => yAt(value, yMax.value, height.value, PADDING)

const linePath = (points: number[]) =>
  buildLinePath(points, props.dates.length, yMax.value, width.value, height.value, PADDING)

const tooltipStyle = computed(() => {
  if (hoverIndex.value === null) return {}
  const x = xPos(hoverIndex.value)
  const flip = x > width.value - 150
  return {
    left: `${Math.round(flip ? x - 140 : x + 12)}px`,
    top: `${PADDING.top}px`,
  }
})

function onMove(event: MouseEvent) {
  if (!svgRef.value || props.dates.length === 0) return
  const rect = svgRef.value.getBoundingClientRect()
  hoverIndex.value = indexAtX(
    event.clientX - rect.left,
    props.dates.length,
    width.value,
    PADDING,
  )
}

let observer: ResizeObserver | null = null

function measure() {
  const el = wrapRef.value
  if (el) width.value = Math.max(320, el.clientWidth)
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && wrapRef.value) {
    observer = new ResizeObserver(measure)
    observer.observe(wrapRef.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

watch(
  () => props.dates.length,
  () => {
    hoverIndex.value = null
  },
)
</script>

<style scoped>
.usage-trend {
  width: 100%;
}

.usage-trend__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--space-8) var(--space-4);
  color: var(--text-tertiary);
  font-size: 13px;
}

.usage-trend__empty-hint {
  font-size: 12px;
}

.usage-trend__legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  margin-bottom: var(--space-2);
}

.usage-trend__legend-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.usage-trend__legend-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex: none;
}

.usage-trend__legend-name {
  color: var(--text-secondary);
}

.usage-trend__legend-value {
  color: var(--text-primary);
  font-family: var(--font-family-mono);
  font-weight: 600;
}

.usage-trend__legend-failed {
  padding: 0 5px;
  border-radius: var(--radius-sm);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: 11px;
  line-height: 16px;
}

.usage-trend__legend-detail {
  display: none;
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 3;
  min-width: 220px;
  max-width: 360px;
  margin-top: 4px;
  padding: var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  color: var(--text-secondary);
  line-height: 1.7;
  white-space: normal;
}

.usage-trend__legend-item:hover .usage-trend__legend-detail {
  display: block;
}

.usage-trend__legend-detail-line {
  font-size: 12px;
}

.usage-trend__plot {
  position: relative;
}

.usage-trend__svg {
  display: block;
  width: 100%;
}

.usage-trend__grid {
  stroke: var(--border-color);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

.usage-trend__axis-label {
  fill: var(--text-tertiary);
  font-size: 11px;
  font-family: var(--font-family-mono);
}

.usage-trend__line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.usage-trend__cursor {
  stroke: var(--border-color-strong);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

.usage-trend__dot {
  stroke: var(--bg-surface);
  stroke-width: 1.5;
}

.usage-trend__tooltip {
  position: absolute;
  pointer-events: none;
  min-width: 128px;
  padding: var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  font-size: 12px;
  z-index: 2;
}

.usage-trend__tooltip-title {
  margin-bottom: 4px;
  color: var(--text-tertiary);
  font-family: var(--font-family-mono);
}

.usage-trend__tooltip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  line-height: 1.8;
}

.usage-trend__tooltip-name {
  color: var(--text-secondary);
  flex: 1;
}

.usage-trend__tooltip-value {
  color: var(--text-primary);
  font-family: var(--font-family-mono);
  font-weight: 600;
}
</style>
