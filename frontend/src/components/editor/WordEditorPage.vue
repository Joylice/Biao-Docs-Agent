<template>
  <div class="word-page">
    <!-- 顶栏：返回 + 章节信息 + 保存 -->
    <header class="word-page__header">
      <div class="word-page__header-left">
        <a-button
          size="small"
          aria-label="返回分工页"
          @click="handleBack"
        >
          <template #icon>
            <ArrowLeftOutlined />
          </template>
          返回
        </a-button>
        <a-divider type="vertical" />
        <a-tag color="blue">
          {{ chapterNo }}
        </a-tag>
        <span class="word-page__chapter-title">{{ chapterTitle || '章节编辑' }}</span>
      </div>
      <div class="word-page__header-right">
        <span
          class="word-page__save-hint"
          :class="`word-page__save-hint--${saveStatus}`"
        >
          {{ saveHint }}
        </span>
        <a-button
          size="small"
          type="primary"
          :loading="saveStatus === 'saving'"
          aria-label="保存章节内容"
          @click="saveNow"
        >
          保存
        </a-button>
      </div>
    </header>

    <!-- 工具栏 -->
    <WordEditorToolbar
      class="word-page__toolbar"
      :editor="editorInstance"
    />

    <!-- A4 纸面编辑区 -->
    <a-spin
      :spinning="loading"
      wrapper-class-name="word-page__editor-spin"
    >
      <WordEditor
        ref="editorRef"
        class="word-page__editor"
        :content="initialHtml"
        :readonly="loading"
        placeholder="请输入章节内容，支持标题、列表、表格等富文本排版..."
        @update:content="handleContentUpdate"
      />
    </a-spin>

    <!-- 底部状态栏 -->
    <WordEditorStatusBar
      :editor="editorInstance"
      :save-status="saveStatus"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorPage：章节全屏富文本编辑页
 * 路由：/project/:projectId/editor/:chapterNo
 *
 * 数据流：
 * - 加载：fetchChapterContent → content_html 优先，否则 markdownToHtml(content)
 * - 保存：htmlToMarkdown(getHTML()) 得 markdown，连同 HTML 双字段 PUT 保存
 * - 自动保存：内容变化 2s 防抖；失败自动重试 2 次；Ctrl+S 手动保存；
 *   beforeunload 拦截未保存离开
 */
import { ref, computed, unref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined } from '@ant-design/icons-vue'
import WordEditor from './WordEditor.vue'
import WordEditorToolbar from './WordEditorToolbar.vue'
import WordEditorStatusBar from './WordEditorStatusBar.vue'
import type { SaveStatus } from './WordEditorStatusBar.vue'
import { markdownToHtml, htmlToMarkdown } from './utils/markdown-converter'
import {
  fetchChapterContent,
  saveChapterContent,
  fetchChapterAssignments,
} from '@/api'
import type { AssignmentNode } from '@/types'
import { useHotkeys } from '@/composables/useHotkeys'

/* ---------------- 路由参数 ---------------- */
const route = useRoute()
const router = useRouter()
const projectId = String(route.params.projectId ?? '')
const chapterNo = String(route.params.chapterNo ?? '')

/* ---------------- 状态 ---------------- */
const editorRef = ref<InstanceType<typeof WordEditor> | null>(null)
/** 编辑器实例（透传给工具栏/状态栏） */
const editorInstance = computed(() => unref(editorRef.value?.editor))

const loading = ref(false)
const initialHtml = ref('')
const chapterTitle = ref('')

/** 保存状态机：idle → saving → saved/error */
const saveStatus = ref<SaveStatus>('idle')
/** 是否有未保存改动（对比最近一次成功保存的 HTML） */
const dirty = ref(false)
const lastSavedHtml = ref('')
/** 自动保存失败重试计数（上限 2 次） */
const retryCount = ref(0)

/* 定时器句柄 */
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null

/** 自动保存防抖时长（ms） */
const AUTOSAVE_DEBOUNCE_MS = 2000
/** 失败重试延迟（ms） */
const RETRY_DELAY_MS = 1500
/** 自动保存最大重试次数 */
const MAX_RETRY = 2

const SAVE_HINT: Record<SaveStatus, string> = {
  idle: '有改动未保存时将自动保存',
  saving: '保存中...',
  saved: '已保存',
  error: '保存失败，自动重试中...',
}
const saveHint = computed(() =>
  dirty.value && saveStatus.value === 'idle' ? '待自动保存' : SAVE_HINT[saveStatus.value],
)

/* ---------------- 内容变化 → 防抖自动保存 ---------------- */
const handleContentUpdate = (html: string) => {
  dirty.value = html !== lastSavedHtml.value
  if (!dirty.value) {
    // 内容回退到上次保存状态：取消待执行的自动保存
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer)
      autoSaveTimer = null
    }
    return
  }
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => {
    void doSave('auto')
  }, AUTOSAVE_DEBOUNCE_MS)
}

/* ---------------- 保存核心逻辑 ---------------- */
/**
 * 执行保存：getHTML → htmlToMarkdown 得 markdown，双字段提交。
 * @param source auto=自动保存（静默失败重试）；manual=手动保存（结果有提示）
 */
const doSave = async (source: 'auto' | 'manual') => {
  const instance = editorRef.value
  if (!instance || loading.value || saveStatus.value === 'saving') return
  if (!dirty.value && source === 'auto') return

  saveStatus.value = 'saving'
  try {
    const html = instance.getHTML()
    const markdown = htmlToMarkdown(html)
    await saveChapterContent(projectId, chapterNo, {
      content: markdown,
      content_html: html,
    })
    lastSavedHtml.value = html
    dirty.value = false
    retryCount.value = 0
    saveStatus.value = 'saved'
    if (source === 'manual') {
      message.success('保存成功')
    }
  } catch {
    saveStatus.value = 'error'
    if (retryCount.value < MAX_RETRY) {
      // 自动重试：延迟后重新触发
      retryCount.value++
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = setTimeout(() => {
        void doSave(source)
      }, RETRY_DELAY_MS)
    } else if (source === 'manual') {
      message.error('保存失败，请稍后重试')
    }
  }
}

/** 手动保存（Ctrl+S / 保存按钮）：先清掉待执行的自动保存 */
const saveNow = () => {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
  void doSave('manual')
}

useHotkeys([
  {
    combo: 'ctrl+s',
    allowInInput: true,
    handler: saveNow,
  },
])

/* ---------------- 数据加载 ---------------- */

/** 在分工树中递归查找 chapter_no 对应的标题 */
const findChapterTitle = (nodes: AssignmentNode[], target: string): string => {
  for (const node of nodes) {
    if (node.chapter_no === target) return node.title
    if (node.children?.length) {
      const found = findChapterTitle(node.children, target)
      if (found) return found
    }
  }
  return ''
}

const loadChapter = async () => {
  loading.value = true
  try {
    const [contentRes, assignmentsRes] = await Promise.all([
      fetchChapterContent(projectId, chapterNo),
      fetchChapterAssignments(projectId),
    ])
    const data = contentRes.data.data
    // content_html 优先；缺失时将 markdown 转 HTML 供富文本编辑
    initialHtml.value = data?.content_html || (data?.content ? markdownToHtml(data.content) : '')
    lastSavedHtml.value = initialHtml.value
    chapterTitle.value = findChapterTitle(assignmentsRes.data.data?.items ?? [], chapterNo)
  } catch {
    message.error('章节内容加载失败')
  } finally {
    loading.value = false
  }
}

/* ---------------- 返回 / 生命周期 ---------------- */
const handleBack = () => {
  void router.push({ name: 'Division', params: { projectId } })
}

/** 页面关闭/刷新时拦截未保存内容 */
const handleBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  void loadChapter()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (retryTimer) clearTimeout(retryTimer)
})
</script>

<style scoped>
.word-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-app);
}

/* 顶栏 */
.word-page__header {
  flex: 0 0 auto;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}

.word-page__header-left,
.word-page__header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.word-page__chapter-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-primary);
}

/* 保存状态提示（顶栏右侧小字） */
.word-page__save-hint {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}
.word-page__save-hint--saving {
  color: var(--color-primary);
}
.word-page__save-hint--saved {
  color: var(--color-success);
}
.word-page__save-hint--error {
  color: var(--color-error);
}

/* 工具栏 */
.word-page__toolbar {
  flex: 0 0 auto;
}

/* 编辑区：占满剩余高度；spin 包裹层需要撑满 */
.word-page__editor-spin,
.word-page__editor-spin :deep(.ant-spin-container) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.word-page__editor {
  flex: 1;
  min-height: 0;
}
</style>