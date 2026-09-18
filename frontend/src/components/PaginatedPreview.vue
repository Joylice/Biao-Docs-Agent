<template>
  <div
    ref="rootRef"
    class="paged-preview"
    :class="fill ? 'paged-preview--fill' : 'paged-preview--auto'"
  >
    <!-- 内容为空：空态 -->
    <div v-if="!hasContent" class="paged-preview__empty">
      <FileTextOutlined class="paged-preview__empty-icon" />
      <span>暂无内容可预览</span>
    </div>

    <!-- 分页滚动区 -->
    <div v-else class="paged-preview__scroll">
      <div
        v-for="(page, i) in pages"
        :key="i"
        class="paged-preview__sheet"
        :class="{ 'paged-preview__sheet--overflow': page.overflow }"
        :style="sheetStyleOf(page)"
      >
        <div
          class="paged-preview__content"
          :style="contentStyle"
          v-html="page.html"
        />
        <div
          v-if="showPageNumbers"
          class="paged-preview__footer"
        >
          — {{ i + 1 }} —
        </div>
      </div>
    </div>

    <!-- 离屏测量容器（与纸面内容同宽同样式，用于高度测量与文本切分） -->
    <div
      ref="measureRef"
      class="paged-preview__measure"
      :style="{ '--paged-content-w': contentW + 'px' }"
      aria-hidden="true"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { FileTextOutlined } from '@ant-design/icons-vue'
import {
  textLength,
  isSplittableTextBlock,
  truncateToChars,
  splitAtChars,
  hasVisibleContent,
} from '@/utils/pageSplit'

interface PageUnit {
  html: string
  overflow: boolean
}

const props = withDefaults(
  defineProps<{
    /** 需要分页展示的 HTML（块级元素序列） */
    html: string
    /** 是否显示页脚页码 */
    showPageNumbers?: boolean
    /** 纸面最大宽度（px，A4 210mm@96dpi ≈ 793） */
    maxWidth?: number
    /** fill：自身高度撑满并滚动（编辑器内）；auto：随内容流堆叠（全文预览/长页滚动） */
    fill?: boolean
  }>(),
  {
    showPageNumbers: true,
    maxWidth: 793,
    fill: true,
  },
)

const rootRef = ref<HTMLElement>()
const measureRef = ref<HTMLDivElement>()

const pages = ref<PageUnit[]>([])
const hasContent = computed(() => (props.html || '').trim().length > 0)

// 纸面尺寸（px）：宽取容器可用宽，高按 A4 比例 210:297
const pageW = ref(props.maxWidth)
const PAGE_PAD = 52
const FOOTER_H = 26
const sheetH = computed(() => Math.round(pageW.value * (297 / 210)))
const contentW = computed(() => Math.max(120, pageW.value - PAGE_PAD * 2))
const capH = computed(() => sheetH.value - PAGE_PAD * 2 - FOOTER_H)

/** 单页样式：overflow 页（内容超高兜底）不锁 minHeight，允许自然增高 */
const sheetStyleOf = (page: PageUnit) => ({
  width: `${pageW.value}px`,
  minHeight: page.overflow ? 'auto' : `${sheetH.value}px`,
})
const contentStyle = computed(() => ({
  padding: `${PAGE_PAD}px`,
  paddingBottom: `${PAGE_PAD + FOOTER_H}px`,
}))

let resizeTimer: number | undefined

/** 容器宽自适应：宽 = min(容器宽, maxWidth)，再按 A4 比例重建分页 */
const syncWidth = () => {
  const root = rootRef.value
  if (!root) return
  const w = Math.floor(root.clientWidth)
  const next = Math.max(320, Math.min(w, props.maxWidth))
  if (next !== pageW.value) {
    pageW.value = next
    void rebuild()
  }
}

/* ---------------- 分页引擎（真实渲染测量） ---------------- */

const measureEl = (el: Element): number => {
  const m = measureRef.value
  if (!m) return 0
  m.innerHTML = ''
  m.appendChild(el)
  const h = m.scrollHeight
  m.innerHTML = ''
  return h
}

const newSheet = (): { html: string[]; overflow: boolean; usedH: number } => ({
  html: [],
  overflow: false,
  usedH: 0,
})

/**
 * 计算元素单独（空容器、无 margin collapse 干扰）渲染高度。
 * 使用 clone，避免影响原元素。
 */
const blockHeight = (el: Element): number => measureEl(el.cloneNode(true) as Element)

/**
 * 二分找"高度不超过预算的最大字符前缀"。
 * 字符级切分（v1：跨页断点可能在行中，后续可精化为行首对齐，
 * 观感影响仅限超长段落跨页处）。
 */
const findBestFitChars = (el: Element, budget: number): number => {
  const len = textLength(el)
  if (len === 0) return 0
  const hOf = (chars: number): number => {
    const clone = el.cloneNode(true) as Element
    truncateToChars(clone, chars)
    return blockHeight(clone)
  }
  // 最大 fit 前缀（h 单调不减，二分上界；字符级切分，行级对齐待后续精化）
  let lo = 0
  let hi = len
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (hOf(mid) <= budget) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** 超长文本块按页切分为多段（每段可单独放入一页），原子块返回 null */
const splitOverflowText = (el: Element): Element[] | null => {
  if (!isSplittableTextBlock(el)) return null
  const parts: Element[] = []
  let rest = el.cloneNode(true) as Element
  let guard = 0
  while (textLength(rest) > 0 && guard++ < 200) {
    const best = findBestFitChars(rest, capH.value)
    if (best <= 0) break
    const [head, tail] = splitAtChars(rest, best)
    if (textLength(head) > 0) parts.push(head)
    rest = tail
    if (parts.length > 1 && textLength(tail) === 0) break
  }
  if (textLength(rest) > 0) parts.push(rest)
  return parts
}

const rebuild = async (): Promise<void> => {
  await nextTick()
  const root = rootRef.value
  if (!root) return
  // 更新宽（若测量容器尚未就位则跳过）
  const source = (props.html || '').trim()
  if (!source) {
    pages.value = []
    return
  }
  const doc = document.createElement('div')
  doc.innerHTML = source
  const blocks = Array.from(doc.children).filter((el) => hasVisibleContent(el))
  if (blocks.length === 0) {
    pages.value = []
    return
  }

  const output: PageUnit[] = []
  let cur = newSheet()

  const flush = () => {
    if (cur.html.length > 0) {
      output.push({ html: cur.html.join(''), overflow: cur.overflow })
    }
    cur = newSheet()
  }

  for (const el of blocks) {
    const h = blockHeight(el)
    // 页可容纳（容差 2px，吸收行高取整误差）
    if (cur.html.length === 0 || cur.usedH + h <= capH.value + 2) {
      cur.html.push(el.outerHTML)
      cur.usedH += h
      continue
    }
    // 放不下：若为文本块 → 切分到本页剩余空间
    if (isSplittableTextBlock(el)) {
      // 剩余可用高度
      const remain = Math.max(1, capH.value - cur.usedH)
      const best = findBestFitChars(el, remain)
      if (best > 0 && textLength(el) > best) {
        const [head, tail] = splitAtChars(el, best)
        if (textLength(head) > 0) {
          cur.html.push(head.outerHTML)
          cur.usedH += blockHeight(head)
        }
        flush()
        // 尾部可能仍超一页 → 继续切分
        if (textLength(tail) > 0) {
          const parts = splitOverflowText(tail) ?? [tail]
          for (const p of parts) {
            if (cur.html.length > 0 && cur.usedH + blockHeight(p) > capH.value + 2) flush()
            cur.html.push(p.outerHTML)
            cur.usedH += blockHeight(p)
          }
        }
        continue
      }
      // 切不下（本页连 1 字符也放不下）→ 整段换页
      flush()
      const parts = splitOverflowText(el) ?? [el]
      for (const p of parts) {
        if (cur.html.length > 0 && cur.usedH + blockHeight(p) > capH.value + 2) flush()
        cur.html.push(p.outerHTML)
        cur.usedH += blockHeight(p)
      }
      continue
    }
    // 原子块（表格/图片/列表等）：整块换页；仍超一页 → 独占页放行（页自适应增高）
    flush()
    if (h > capH.value + 2) {
      cur.html.push(el.outerHTML)
      cur.overflow = true
      flush()
    } else {
      cur.html.push(el.outerHTML)
      cur.usedH = h
    }
  }
  flush()
  pages.value = output
}

watch(
  () => props.html,
  () => void rebuild(),
  { immediate: true },
)

let ro: ResizeObserver | undefined
onMounted(() => {
  syncWidth()
  ro = new ResizeObserver(() => {
    window.clearTimeout(resizeTimer)
    resizeTimer = window.setTimeout(syncWidth, 120)
  })
  if (rootRef.value) ro.observe(rootRef.value)
})
onBeforeUnmount(() => {
  ro?.disconnect()
  window.clearTimeout(resizeTimer)
})
</script>

<style scoped>
.paged-preview {
  min-height: 200px;
}

/* fill：自身撑满并滚动（编辑器内嵌场景） */
.paged-preview--fill {
  height: 100%;
  overflow: auto;
  background: var(--bg-app, #f8fafc);
}

/* auto：随内容流堆叠（全文预览等外部统一滚动场景），纸面阴影自带层次 */
.paged-preview--auto {
  height: auto;
  overflow: visible;
  background: transparent;
}

.paged-preview__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-tertiary, #94a3b8);
  font-size: 13px;
}

.paged-preview__empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.paged-preview__scroll {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  padding: 24px 12px 48px;
}

/* A4 纸面：恒白底深字，不随主题变化 */
.paged-preview__sheet {
  position: relative;
  flex-shrink: 0;
  box-sizing: border-box;
  background: #ffffff;
  color: #1f2329;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.16), 0 1px 3px rgba(15, 23, 42, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.paged-preview__sheet--overflow {
  min-height: auto;
}

.paged-preview__content {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  overflow: hidden;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

.paged-preview__footer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 8px;
  height: 18px;
  text-align: center;
  font-size: 11px;
  color: #b6bcc6;
  user-select: none;
  pointer-events: none;
}

.paged-preview__measure {
  position: absolute;
  top: 0;
  left: -10000px;
  visibility: hidden;
  pointer-events: none;
  width: var(--paged-content-w, 689px);
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

/* ---------- 纸面内富文本排版（浅色主题恒用，与 WordEditor 观感对齐） ---------- */
.paged-preview__content :deep(h1),
.paged-preview__content :deep(h2),
.paged-preview__content :deep(h3),
.paged-preview__content :deep(h4),
.paged-preview__content :deep(h5),
.paged-preview__content :deep(h6) {
  color: var(--text-primary);
  font-weight: 700;
  line-height: 1.4;
  margin: 1.1em 0 0.5em;
  page-break-after: avoid;
  break-after: avoid;
}

.paged-preview__content :deep(h1) { font-size: 22px; text-align: center; margin-top: 0.4em; }
.paged-preview__content :deep(h2) { font-size: 18px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
.paged-preview__content :deep(h3) { font-size: 16px; }
.paged-preview__content :deep(h4) { font-size: 15px; }
.paged-preview__content :deep(h5) { font-size: 14px; }
.paged-preview__content :deep(h6) { font-size: 13px; color: #374151; }

.paged-preview__content :deep(p) {
  margin: 0.35em 0;
  text-indent: 0;
}

.paged-preview__content :deep(ul),
.paged-preview__content :deep(ol) {
  padding-left: 2em;
  margin: 0.4em 0;
}

.paged-preview__content :deep(li) {
  margin: 0.15em 0;
}

.paged-preview__content :deep(img) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0.6em auto;
  border-radius: 2px;
}

.paged-preview__content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 13px;
}

.paged-preview__content :deep(th),
.paged-preview__content :deep(td) {
  border: 1px solid #d1d5db;
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}

.paged-preview__content :deep(th) {
  background: var(--bg-surface-hover);
  font-weight: 600;
  color: var(--text-primary);
}

.paged-preview__content :deep(blockquote) {
  margin: 0.6em 0;
  padding: 4px 14px;
  border-left: 4px solid #bfdbfe;
  color: #374151;
  background: #f8fafc;
}

.paged-preview__content :deep(pre) {
  background: #f6f8fa;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  padding: 10px 12px;
  overflow: auto;
  font-size: 12.5px;
  line-height: 1.6;
}

.paged-preview__content :deep(code) {
  font-family: Consolas, 'Courier New', monospace;
  background: rgba(127, 127, 127, 0.12);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.92em;
}

.paged-preview__content :deep(hr) {
  border: none;
  border-top: 1px dashed #cbd5e1;
  margin: 1em 0;
}
</style>
