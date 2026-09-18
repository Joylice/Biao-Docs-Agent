<template>
  <div class="chapter-preview">
    <div class="chapter-preview__header">
      <!-- 预览模式切换：章节预览 / 全文预览（全文需全部章节通过评审） -->
      <a-radio-group
        v-model:value="mode"
        size="small"
        button-style="solid"
        class="chapter-preview__mode"
      >
        <a-radio-button value="chapter">章节预览</a-radio-button>
        <a-radio-button
          value="full"
          :disabled="!canFull"
        >
          全文预览
        </a-radio-button>
      </a-radio-group>
      <a-tag
        v-if="!canFull"
        color="orange"
        class="chapter-preview__hint"
      >
        已通过 {{ approvedCount }}/{{ outline.length }} 章，全部通过评审后可预览全文
      </a-tag>
      <div class="chapter-preview__actions">
        <a-button
          v-if="mode === 'chapter' && selectedChapter"
          size="small"
          type="primary"
          ghost
          @click="$emit('go-division')"
        >
          去编制
        </a-button>
      </div>
    </div>

    <div
      ref="contentRef"
      class="chapter-preview__content"
    >
      <!-- 章节预览：按左侧树选中章节加载单章内容 -->
      <template v-if="mode === 'chapter'">
        <template v-if="selectedChapter">
          <div class="chapter-preview__card">
            <LoadingSkeleton
              v-if="contentLoading"
              :rows="6"
            />
            <!-- 内容已是 HTML（content_html 或 markdown 转换后），直接 v-html 渲染 -->
            <div
              v-else-if="chapterContent"
              class="chapter-preview__html"
              v-html="chapterContent"
            />
            <EmptyState
              v-else
              description="该章节尚未编制，请前往分工页编制内容"
            >
              <template #action>
                <a-button
                  type="primary"
                  size="small"
                  @click="$emit('go-division')"
                >
                  去编制
                </a-button>
              </template>
            </EmptyState>
          </div>
        </template>
        <EmptyState
          v-else
          description="从左侧大纲选择章节查看内容"
        />
      </template>

      <!-- 全文预览：全部章节通过评审后按大纲顺序拼接整篇方案 -->
      <template v-else>
        <div
          v-if="fullLoading"
          class="chapter-preview__card"
        >
          <LoadingSkeleton :rows="6" />
        </div>
        <div
          v-else-if="outline.length > 0"
          class="chapter-preview__full"
        >
          <div
            v-for="chapter in outline"
            :id="`full-${chapter.chapter_no}`"
            :key="chapter.chapter_no"
            class="chapter-preview__full-chapter"
          >
            <div class="chapter-preview__full-head">
              <span class="chapter-preview__full-no">{{ chapter.chapter_no }}</span>
              <span class="chapter-preview__full-title">{{ chapter.title }}</span>
              <a-tag
                v-if="!fullHtmls[chapter.chapter_no]"
                color="warning"
                class="chapter-preview__full-tag"
              >
                暂无内容
              </a-tag>
            </div>
            <div class="chapter-preview__card">
              <div
                v-if="fullHtmls[chapter.chapter_no]"
                class="chapter-preview__html"
                v-html="fullHtmls[chapter.chapter_no]"
              />
              <EmptyState
                v-else
                description="该章节暂无内容"
              />
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { fetchChapterContent } from '@/api'
import { markdownToHtml } from '@/utils/markdown-converter'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import type { OutlineItem, AssignmentNode } from '@/types'

const props = defineProps<{
  selectedChapter: string
  projectId: string
  /** 大纲章节（用于全文预览按序拼接与全过审判定） */
  outline: OutlineItem[]
  /** 章节分工状态映射（status=approved 视为通过评审） */
  assignmentMap: Map<string, AssignmentNode>
}>()

defineEmits<{
  (e: 'go-division'): void
}>()

/** 预览模式：章节（单章） / 全文（整篇拼接） */
const mode = ref<'chapter' | 'full'>('chapter')
const contentRef = ref<HTMLElement | null>(null)

/* ---------------- 章节预览 ---------------- */
const chapterContent = ref('')
const contentLoading = ref(false)
/** 请求序号：补拉（assignmentMap 就绪）与点击并发时以最后一次为准 */
let loadSeq = 0

/* ---------------- 全文预览 ---------------- */
const fullHtmls = ref<Record<string, string>>({})
const fullLoading = ref(false)
const fullLoaded = ref(false)

/** 全部章节均通过评审（approved）才可启用全文预览 */
const canFull = computed(
  () =>
    props.outline.length > 0 &&
    props.outline.every((c) => props.assignmentMap.get(c.chapter_no)?.status === 'approved'),
)

const approvedCount = computed(
  () =>
    props.outline.filter((c) => props.assignmentMap.get(c.chapter_no)?.status === 'approved')
      .length,
)

/** 拉取单章/子节内容（章节预览模式）：
 * - 子节编号（含 "."）：分工内容真源，直接取该 assignment
 * - 章编号：若章级行聚合了子节（分工模式）→ 按子节自然序拼接全部内容；
 *   否则（章级直接分配 / 无分工）→ 单取该章
 */
const loadChapter = async (no: string) => {
  if (!no) { chapterContent.value = ''; return }
  const seq = ++loadSeq
  contentLoading.value = true
  chapterContent.value = ''
  try {
    const children = props.assignmentMap.get(no)?.children
    if (children?.length) {
      const results = await Promise.all(
        children.map(async (child) => {
          const { data } = await fetchChapterContent(props.projectId, child.chapter_no)
          const html = data.data?.content_html || markdownToHtml(data.data?.content || '')
          const title = child.title || ''
          const hasContent = html && html.replace(/<[^>]*>/g, '').trim().length > 0
          const body = hasContent
            ? html
            : '<p style="color:#999">该子节尚未编制，请前往分工页编制内容</p>'
          return `<div class="chapter-preview__sec">
              ${title ? `<div class="chapter-preview__sec-title">${title}</div>` : ''}
              ${body}
            </div>`
        }),
      )
      if (seq === loadSeq) chapterContent.value = results.join('')
    } else {
      const { data } = await fetchChapterContent(props.projectId, no)
      // 优先使用 content_html，没有则将 Markdown 转为 HTML
      const html = data.data?.content_html || markdownToHtml(data.data?.content || '')
      // 仅有空标签（如 <p></p>）视为无内容 → 显示引导空态
      if (seq === loadSeq) {
        chapterContent.value = html && html.replace(/<[^>]*>/g, '').trim() ? html : ''
      }
    }
  } catch {
    if (seq === loadSeq) chapterContent.value = ''
  } finally {
    if (seq === loadSeq) contentLoading.value = false
  }
}

/** 拉取全部章节内容（全文预览模式，按大纲顺序；带缓存避免重复请求）：
 * 分工模式章级聚合子节（同 loadChapter），否则单取章号内容 */
const loadFull = async () => {
  if (fullLoaded.value) return
  fullLoading.value = true
  try {
    const results = await Promise.allSettled(
      props.outline.map(async (c) => {
        const node = props.assignmentMap.get(c.chapter_no)
        const children = node?.children
        if (children?.length) {
          const secs = await Promise.all(
            children.map(async (child) => {
              const { data } = await fetchChapterContent(props.projectId, child.chapter_no)
              const html = data.data?.content_html || markdownToHtml(data.data?.content || '')
              const title = child.title || ''
              const hasContent = html && html.replace(/<[^>]*>/g, '').trim().length > 0
              const body = hasContent
                ? html
                : '<p style="color:#999">该子节尚未编制</p>'
              return `<div class="chapter-preview__sec">
                  ${title ? `<div class="chapter-preview__sec-title">${title}</div>` : ''}
                  ${body}
                </div>`
            }),
          )
          return { no: c.chapter_no, html: secs.join('') }
        }
        const { data } = await fetchChapterContent(props.projectId, c.chapter_no)
        return {
          no: c.chapter_no,
          html: data.data?.content_html || markdownToHtml(data.data?.content || ''),
        }
      }),
    )
    const map: Record<string, string> = {}
    for (const r of results) {
      if (r.status === 'fulfilled') map[r.value.no] = r.value.html
    }
    fullHtmls.value = map
    fullLoaded.value = true
  } finally {
    fullLoading.value = false
  }
}

/* ---------------- 联动 ---------------- */
watch(mode, (m) => {
  // 首次切到全文时加载全部章节内容
  if (m === 'full' && !fullLoaded.value) loadFull()
})

watch(
  () => props.selectedChapter,
  async (no) => {
    // 全文模式：点击左侧树 → 滚动定位到对应章节
    if (mode.value === 'full') {
      await nextTick()
      if (no) {
        contentRef.value
          ?.querySelector(`#full-${no}`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      return
    }
    await loadChapter(no)
  },
  { immediate: true },
)

/* ---------------- assignmentMap 就绪联动 ---------------- */
// 页面初始 fetchAssignments 晚于 immediate watch：当前选中编号从"无分工记录"
// 变为"有记录"时补拉一次（章级聚合依赖 children；避免默认章首次预览为空）。
// 补拉不看 contentLoading（可能被初始 4004 占位吞掉），由 loadSeq 保证后发覆盖先发。
watch(
  () => props.assignmentMap,
  (map, prev) => {
    if (mode.value !== 'chapter' || !props.selectedChapter) return
    const no = props.selectedChapter
    const prevNode = prev?.get(no)
    const node = map.get(no)
    if (!prevNode && node) loadChapter(no)
  },
)
</script>

<style scoped>
.chapter-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chapter-preview__header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.chapter-preview__mode {
  flex-shrink: 0;
}

.chapter-preview__hint {
  font-size: 12px;
  line-height: 20px;
  margin-right: 0;
}

.chapter-preview__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
}

.chapter-preview__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.chapter-preview__card {
  min-height: 320px;
  padding: 20px 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

/* ---------------- 全文预览 ---------------- */
.chapter-preview__full {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.chapter-preview__full-chapter {
  scroll-margin-top: 12px;
}

.chapter-preview__full-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.chapter-preview__full-no {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}

.chapter-preview__full-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.chapter-preview__full-tag {
  margin-left: auto;
  font-size: 11px;
}

/* HTML 内容渲染样式：模拟文档阅读体验 */
.chapter-preview__html {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
  word-break: break-word;
}

.chapter-preview__html :deep(h1),
.chapter-preview__html :deep(h2),
.chapter-preview__html :deep(h3),
.chapter-preview__html :deep(h4) {
  margin: 1em 0 0.5em;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.chapter-preview__html :deep(h1) {
  font-size: 20px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 8px;
}

.chapter-preview__html :deep(h2) {
  font-size: 17px;
}

.chapter-preview__html :deep(h3) {
  font-size: 15px;
}

.chapter-preview__html :deep(h4) {
  font-size: 14px;
}

.chapter-preview__html :deep(p) {
  margin: 0.5em 0;
}

.chapter-preview__html :deep(ul),
.chapter-preview__html :deep(ol) {
  padding-left: 1.6em;
  margin: 0.5em 0;
}

.chapter-preview__html :deep(li) {
  margin: 0.25em 0;
}

.chapter-preview__html :deep(blockquote) {
  margin: 0.8em 0;
  padding: 4px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--bg-block);
  color: var(--text-secondary);
  border-radius: 2px;
}

.chapter-preview__html :deep(code) {
  padding: 2px 6px;
  background: var(--bg-block);
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Courier New', monospace;
}

.chapter-preview__html :deep(pre) {
  padding: 12px 16px;
  background: var(--bg-block);
  border-radius: 6px;
  overflow-x: auto;
}

.chapter-preview__html :deep(pre code) {
  padding: 0;
  background: transparent;
}

.chapter-preview__html :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
}

.chapter-preview__html :deep(th),
.chapter-preview__html :deep(td) {
  border: 1px solid var(--border-color);
  padding: 8px 12px;
  text-align: left;
}

.chapter-preview__html :deep(th) {
  background: var(--bg-block);
  font-weight: 600;
}

.chapter-preview__html :deep(a) {
  color: var(--color-primary);
}

.chapter-preview__html :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 1em 0;
}

.chapter-preview__html :deep(img) {
  max-width: 100%;
  border-radius: 4px;
}
</style>
