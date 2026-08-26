<template>
  <div
    class="word-ruler"
    :class="{ 'word-ruler--dark': isDark }"
    ref="rulerRef"
    role="presentation"
    aria-label="水平标尺"
  >
    <!-- 左侧页边距区域（灰色） -->
    <div
      class="word-ruler__margin word-ruler__margin--left"
      :style="{ width: leftMarginPx + 'px' }"
    />

    <!-- 主刻度区域 -->
    <div
      class="word-ruler__track"
      :style="{ width: contentWidthPx + 'px' }"
      @mousedown="handleTrackClick"
    >
      <!-- 厘米刻度线 -->
      <div
        v-for="tick in ticks"
        :key="tick.value"
        class="word-ruler__tick"
        :class="{
          'word-ruler__tick--major': tick.major,
          'word-ruler__tick--mid': tick.mid,
        }"
        :style="{ left: tick.left + 'px' }"
      >
        <span v-if="tick.major" class="word-ruler__tick-label">{{ tick.value }}</span>
      </div>

      <!-- 首行缩进标记（顶部倒三角形） -->
      <div
        class="word-ruler__marker word-ruler__marker--first"
        :style="{ left: firstLineIndentPx + 'px' }"
        @mousedown.stop="startDrag('first', $event)"
        title="首行缩进（拖拽调整）"
      />
    </div>

    <!-- 右侧页边距区域（灰色） -->
    <div
      class="word-ruler__margin word-ruler__margin--right"
      :style="{ width: rightMarginPx + 'px' }"
    />

    <!-- 单位切换按钮 -->
    <button
      class="word-ruler__unit-btn"
      @click="toggleUnit"
      :title="`当前单位：${unit === 'cm' ? '厘米' : '毫米'}`"
    >
      {{ unit === 'cm' ? 'cm' : 'mm' }}
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorRuler：水平标尺组件
 * - 显示厘米/毫米刻度
 * - 首行缩进 / 左缩进 / 右缩进标记
 * - 拖拽调整缩进（通过 emit 通知父组件执行 Tiptap 命令）
 * - 页边距区域灰色显示
 *
 * 设计：标尺宽度 = 纸张内容区宽度（A4 210mm - 左右页边距）
 * 刻度从 0 开始，到内容区宽度结束
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import type { Editor } from '@tiptap/core'

const props = defineProps<{
  /** 编辑器实例 */
  editor?: Editor
  /** 纸张内容区宽度（mm），默认 A4 210mm - 2*25.4mm = 159.2mm */
  contentWidthMm?: number
  /** 左页边距（mm），默认 25.4mm */
  leftMarginMm?: number
  /** 右页边距（mm），默认 25.4mm */
  rightMarginMm?: number
}>()

const emit = defineEmits<{
  (e: 'indent-change', valueEm: number): void
}>()

/* 单位：cm / mm */
const unit = ref<'cm' | 'mm'>('cm')
const toggleUnit = () => {
  unit.value = unit.value === 'cm' ? 'mm' : 'cm'
}

/* 深色模式检测 */
const isDark = ref(false)
const checkDarkMode = () => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
}
let darkObserver: MutationObserver | null = null

/* 标尺 DOM 引用 */
const rulerRef = ref<HTMLDivElement | null>(null)

/* 像素密度：根据标尺实际宽度计算 mm → px 比例 */
const pxPerMm = ref(3.78) // 默认 96dpi: 1mm ≈ 3.78px

const updatePxPerMm = () => {
  if (!rulerRef.value) return
  const track = rulerRef.value.querySelector('.word-ruler__track') as HTMLElement | null
  if (!track) return
  const contentMm = props.contentWidthMm ?? 159.2
  pxPerMm.value = track.offsetWidth / contentMm
}

/* 计算尺寸（px） */
const contentWidthPx = computed(() => (props.contentWidthMm ?? 159.2) * pxPerMm.value)
const leftMarginPx = computed(() => (props.leftMarginMm ?? 25.4) * pxPerMm.value)
const rightMarginPx = computed(() => (props.rightMarginMm ?? 25.4) * pxPerMm.value)

/* 当前段落首行缩进（从编辑器读取，单位 em） */
const currentIndentEm = ref(0)

const updateIndentFromEditor = () => {
  const editor = props.editor
  if (!editor) return
  // 优先取标题，其次段落
  const attrs = editor.isActive('heading')
    ? editor.getAttributes('heading')
    : editor.getAttributes('paragraph')
  const textIndent = attrs.textIndent as string | undefined
  if (textIndent && textIndent.endsWith('em')) {
    currentIndentEm.value = parseFloat(textIndent) || 0
  } else {
    currentIndentEm.value = 0
  }
}

/* 首行缩进标记位置（px）：1em ≈ 当前字体大小 px，默认 16px */
const firstLineIndentPx = computed(() => {
  // 使用编辑器默认字体大小 16px 作为 1em 的近似值
  // 实际应根据当前段落字号计算，这里简化处理
  const emPx = 16
  return currentIndentEm.value * emPx
})

/* 刻度生成 */
interface Tick {
  value: number
  left: number
  major: boolean
  mid: boolean
}

const ticks = computed<Tick[]>(() => {
  const contentMm = props.contentWidthMm ?? 159.2
  const step = unit.value === 'cm' ? 10 : 5 // cm: 每1cm一个大刻度; mm: 每5mm一个大刻度
  const result: Tick[] = []
  for (let mm = 0; mm <= contentMm; mm += 1) {
    const isMajor = mm % step === 0
    const isMid = mm % (step / 2) === 0 && !isMajor
    if (isMajor || isMid || mm % 1 === 0) {
      result.push({
        value: unit.value === 'cm' ? mm / 10 : mm,
        left: mm * pxPerMm.value,
        major: isMajor,
        mid: isMid,
      })
    }
  }
  return result
})

/* 拖拽逻辑 */
let isDragging = false
let dragStartX = 0
let dragStartValue = 0

const startDrag = (_type: 'first', e: MouseEvent) => {
  isDragging = true
  dragStartX = e.clientX
  dragStartValue = currentIndentEm.value
  document.addEventListener('mousemove', handleDrag)
  document.addEventListener('mouseup', stopDrag)
  e.preventDefault()
}

const handleDrag = (e: MouseEvent) => {
  if (!isDragging) return
  // 1em ≈ 16px，每 8px 步进 0.5em
  const deltaEm = (e.clientX - dragStartX) / 16
  let newValue = dragStartValue + deltaEm
  // 边界限制：0 - 8em
  newValue = Math.max(0, Math.min(8, newValue))
  // 取整到 0.5em
  newValue = Math.round(newValue * 2) / 2
  // 实时更新显示
  currentIndentEm.value = newValue
}

const stopDrag = () => {
  if (isDragging) {
    // 提交到编辑器
    emit('indent-change', currentIndentEm.value)
  }
  isDragging = false
  document.removeEventListener('mousemove', handleDrag)
  document.removeEventListener('mouseup', stopDrag)
}

/* 点击刻度区域：设置首行缩进 */
const handleTrackClick = (e: MouseEvent) => {
  const track = e.currentTarget as HTMLElement
  const rect = track.getBoundingClientRect()
  const clickPx = e.clientX - rect.left
  // 1em ≈ 16px
  const clickEm = clickPx / 16
  const roundedEm = Math.round(clickEm * 2) / 2
  const clampedEm = Math.max(0, Math.min(8, roundedEm))
  currentIndentEm.value = clampedEm
  emit('indent-change', clampedEm)
}

/* 监听编辑器事务变化，同步缩进状态 */
let transactionHandler: (() => void) | null = null

const setupEditorListener = () => {
  const editor = props.editor
  if (!editor) return
  transactionHandler = () => updateIndentFromEditor()
  editor.on('transaction', transactionHandler)
  updateIndentFromEditor()
}

onMounted(() => {
  checkDarkMode()
  darkObserver = new MutationObserver(checkDarkMode)
  darkObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

  // 延迟计算 pxPerMm（等待 DOM 渲染）
  requestAnimationFrame(() => {
    updatePxPerMm()
    setupEditorListener()
  })

  window.addEventListener('resize', updatePxPerMm)
})

onBeforeUnmount(() => {
  darkObserver?.disconnect()
  window.removeEventListener('resize', updatePxPerMm)
  if (transactionHandler && props.editor) {
    props.editor.off('transaction', transactionHandler)
  }
  document.removeEventListener('mousemove', handleDrag)
  document.removeEventListener('mouseup', stopDrag)
})
</script>

<style scoped>
.word-ruler {
  display: flex;
  align-items: stretch;
  height: 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
  position: relative;
  user-select: none;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 页边距区域（灰色） */
.word-ruler__margin {
  background: var(--bg-surface-active);
  flex-shrink: 0;
}

/* 主刻度区域 */
.word-ruler__track {
  position: relative;
  flex-shrink: 0;
  cursor: text;
  overflow: hidden;
}

/* 刻度线 */
.word-ruler__tick {
  position: absolute;
  top: 0;
  width: 1px;
  background: var(--border-color);
}
.word-ruler__tick--major {
  height: 10px;
  background: var(--text-secondary);
}
.word-ruler__tick--mid {
  height: 7px;
}
.word-ruler__tick:not(.word-ruler__tick--major):not(.word-ruler__tick--mid) {
  height: 4px;
  opacity: 0.5;
}

/* 刻度标签 */
.word-ruler__tick-label {
  position: absolute;
  top: 10px;
  left: 2px;
  font-size: 9px;
  line-height: 1;
  white-space: nowrap;
}

/* 缩进标记 */
.word-ruler__marker {
  position: absolute;
  width: 0;
  height: 0;
  cursor: pointer;
  z-index: 2;
  transition: filter 0.15s;
}
.word-ruler__marker:hover {
  filter: brightness(1.2);
}

/* 首行缩进：顶部倒三角 */
.word-ruler__marker--first {
  top: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid var(--color-primary);
  transform: translateX(-5px);
}

/* 左缩进：底部正三角 */
.word-ruler__marker--left {
  bottom: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 6px solid var(--color-primary);
  transform: translateX(-5px);
}

/* 右缩进：底部正三角（右侧） */
.word-ruler__marker--right {
  bottom: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 6px solid var(--color-primary);
  transform: translateX(-5px);
}

/* 单位切换按钮 */
.word-ruler__unit-btn {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 9px;
  color: var(--text-secondary);
  cursor: pointer;
  z-index: 3;
}
.word-ruler__unit-btn:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}
</style>
