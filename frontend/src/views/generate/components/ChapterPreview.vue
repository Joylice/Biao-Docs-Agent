<template>
  <div class="chapter-preview">
    <div class="chapter-preview__header">
      <div class="chapter-preview__title">
        <!-- 章节标题由左侧大纲树展示，此处不重复显示 -->
      </div>
      <div class="chapter-preview__actions">
        <a-button
          v-if="selectedChapter"
          size="small"
          type="primary"
          ghost
          @click="$emit('go-division')"
        >
          去编制
        </a-button>
      </div>
    </div>

    <div class="chapter-preview__content">
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchChapterContent } from '@/api'
import { markdownToHtml } from '@/components/editor/utils/markdown-converter'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

const props = defineProps<{
  selectedChapter: string
  projectId: string
}>()

defineEmits<{
  (e: 'go-division'): void
}>()

const chapterContent = ref('')
const contentLoading = ref(false)

watch(
  () => props.selectedChapter,
  async (no) => {
    if (!no) { chapterContent.value = ''; return }
    contentLoading.value = true
    chapterContent.value = ''
    try {
      const { data } = await fetchChapterContent(props.projectId, no)
      // 优先使用 content_html，没有则将 Markdown 转为 HTML
      const html = data.data?.content_html || markdownToHtml(data.data?.content || '')
      chapterContent.value = html
    } catch {
      chapterContent.value = ''
    } finally {
      contentLoading.value = false
    }
  },
  { immediate: true },
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
  justify-content: space-between;
  margin-bottom: 12px;
}

.chapter-preview__title {
  display: flex;
  align-items: center;
  gap: 8px;
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
