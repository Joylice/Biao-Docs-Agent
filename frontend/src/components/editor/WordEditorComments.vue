<template>
  <div
    class="word-comments"
    :class="{ 'word-comments--dark': isDark }"
    role="complementary"
    aria-label="批注面板"
  >
    <div class="word-comments__header">
      <span class="word-comments__title">
        批注
        <a-tag v-if="unresolvedCount > 0" color="red" size="small">{{ unresolvedCount }}</a-tag>
      </span>
      <a-button
        size="small"
        type="text"
        @click="$emit('close')"
        aria-label="关闭批注面板"
      >
        <template #icon>
          <CloseOutlined />
        </template>
      </a-button>
    </div>

    <!-- 工具栏 -->
    <div class="word-comments__toolbar">
      <a-radio-group v-model:value="filter" size="small" button-style="solid">
        <a-radio-button value="all">全部</a-radio-button>
        <a-radio-button value="unresolved">未解决</a-radio-button>
        <a-radio-button value="resolved">已解决</a-radio-button>
      </a-radio-group>
      <a-button
        size="small"
        type="primary"
        :loading="loading"
        :disabled="!hasSelection || loading"
        @click="showAddModal = true"
      >
        <template #icon>
          <PlusOutlined />
        </template>
        添加
      </a-button>
    </div>

    <!-- 批注列表（后端 chapter_annotations 同源：审阅页/分工编辑器共享） -->
    <div class="word-comments__list">
      <div v-if="loading && comments.length === 0" class="word-comments__empty">
        <a-spin size="small" />
        <p>批注加载中...</p>
      </div>
      <div v-else-if="filteredComments.length === 0" class="word-comments__empty">
        <CommentOutlined class="word-comments__empty-icon" />
        <p>暂无批注</p>
        <p class="word-comments__empty-hint">选中文字后点击"添加"创建批注</p>
      </div>

      <div
        v-for="comment in filteredComments"
        :key="comment.id"
        class="word-comments__item"
        :class="{
          'word-comments__item--active': activeCommentId === comment.id,
          'word-comments__item--resolved': comment.resolved,
        }"
        @click="scrollToComment(comment.id)"
      >
        <div class="word-comments__item-header">
          <span class="word-comments__author">{{ comment.author }}</span>
          <span class="word-comments__time">{{ formatTime(comment.createdAt) }}</span>
          <a-tag v-if="comment.resolved" color="green" size="small">已解决</a-tag>
        </div>

        <div v-if="comment.quote" class="word-comments__quote">"{{ comment.quote }}"</div>

        <div class="word-comments__content">{{ comment.content }}</div>

        <!-- 操作按钮 -->
        <div class="word-comments__actions" @click.stop>
          <a-button
            v-if="!comment.resolved"
            size="small"
            type="text"
            @click="resolveComment(comment.id)"
          >
            <template #icon><CheckOutlined /></template>
            解决
          </a-button>
          <a-button
            v-else
            size="small"
            type="text"
            @click="reopenComment(comment.id)"
          >
            <template #icon><ReloadOutlined /></template>
            重新打开
          </a-button>
          <a-popconfirm
            title="确定删除此批注？"
            @confirm="deleteComment(comment.id)"
          >
            <a-button size="small" type="text" danger>
              <template #icon><DeleteOutlined /></template>
              删除
            </a-button>
          </a-popconfirm>
        </div>
      </div>
    </div>

    <!-- 添加批注弹窗 -->
    <a-modal
      v-model:open="showAddModal"
      title="添加批注"
      ok-text="添加"
      cancel-text="取消"
      :confirm-loading="adding"
      @ok="submitAddComment"
    >
      <div v-if="selectedText" class="word-comments__add-quote">
        <span class="word-comments__add-label">引用文本：</span>
        <span class="word-comments__add-quote-text">"{{ selectedText }}"</span>
      </div>
      <a-textarea
        v-model:value="newCommentContent"
        :rows="4"
        placeholder="输入批注内容..."
      />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorComments：分工编辑器批注面板（2026-09-03 后端同源改造）.
 *
 * 数据源：后端 /chapters/{no}/annotations（chapter_annotations 表），与审阅页批注
 * 同库同章节号 → 审阅页添加的批注在此处可见、可解决/删除；新增批注审阅页同步可见。
 * 原 localStorage 本地演示（useComments，含回复线程）移除：后端无 replies 模型，
 * 回复能力降级为新增独立批注（与审阅页一致）。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  CloseOutlined,
  PlusOutlined,
  CommentOutlined,
  CheckOutlined,
  ReloadOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import { useServerAnnotations } from '@/composables/useServerAnnotations'

const props = defineProps<{
  editor?: Editor
  projectId: string
  chapterNo: string
}>()

defineEmits<{
  (e: 'close'): void
}>()

/* 深色模式 */
const isDark = ref(false)
const checkDarkMode = () => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
}
let darkObserver: MutationObserver | null = null

/* 事务版本号：选中态随编辑器事务实时刷新 */
const version = ref(0)
const bump = () => { version.value++ }

/* 是否有选中文本 */
const hasSelection = computed(() => {
  void version.value
  const ed = props.editor
  if (!ed) return false
  return !ed.state.selection.empty
})

/* 选中文本 */
const selectedText = computed(() => {
  void version.value
  const ed = props.editor
  if (!ed || ed.state.selection.empty) return ''
  const { from, to } = ed.state.selection
  return ed.state.doc.textBetween(from, to, ' ')
})

/* 后端批注数据域 */
const {
  comments,
  filteredComments,
  activeCommentId,
  filter,
  unresolvedCount,
  loading,
  load,
  addComment,
  deleteComment,
  resolveComment,
  reopenComment,
  scrollToComment,
} = useServerAnnotations(props.projectId, props.chapterNo, () => props.editor)

/* 添加批注弹窗 */
const showAddModal = ref(false)
const newCommentContent = ref('')
const adding = ref(false)

const submitAddComment = async () => {
  if (!newCommentContent.value.trim()) return
  adding.value = true
  try {
    await addComment(newCommentContent.value.trim())
    newCommentContent.value = ''
    showAddModal.value = false
  } finally {
    adding.value = false
  }
}

/* 格式化时间（epoch ms） */
const formatTime = (timestamp: number): string => {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - timestamp

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`

  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
}

/* 生命周期 */
let transactionHandler: (() => void) | null = null

onMounted(() => {
  checkDarkMode()
  darkObserver = new MutationObserver(checkDarkMode)
  darkObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

  if (props.editor) {
    transactionHandler = bump
    props.editor.on('transaction', transactionHandler)
  }
  load()
})

onBeforeUnmount(() => {
  darkObserver?.disconnect()
  if (props.editor && transactionHandler) {
    props.editor.off('transaction', transactionHandler)
  }
})
</script>

<style scoped>
.word-comments {
  width: 300px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-color);
  font-size: var(--font-size-sm);
}

.word-comments__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.word-comments__title {
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.word-comments__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
  gap: var(--space-2);
}

.word-comments__list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.word-comments__empty {
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--text-tertiary);
}
.word-comments__empty-icon {
  font-size: 32px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}
.word-comments__empty p {
  margin: var(--space-1) 0;
}
.word-comments__empty-hint {
  font-size: var(--font-size-xs);
  opacity: 0.7;
}

.word-comments__item {
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  background: var(--bg-surface-active);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}
.word-comments__item:hover {
  border-color: var(--color-primary);
}
.word-comments__item--active {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-light);
}
.word-comments__item--resolved {
  opacity: 0.7;
}

.word-comments__item-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.word-comments__author {
  font-weight: 600;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.word-comments__time {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  flex: 1;
}

.word-comments__quote {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  background: var(--bg-app);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-xs);
  margin-bottom: var(--space-2);
  border-left: 2px solid var(--color-primary);
}

.word-comments__content {
  color: var(--text-primary);
  line-height: 1.5;
  margin-bottom: var(--space-2);
}

.word-comments__actions {
  display: flex;
  gap: var(--space-1);
  margin-top: var(--space-2);
  flex-wrap: wrap;
}

.word-comments__add-quote {
  margin-bottom: var(--space-3);
}

.word-comments__add-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.word-comments__add-quote-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  background: var(--bg-surface-active);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-xs);
  display: inline-block;
  margin-top: var(--space-1);
}
</style>
