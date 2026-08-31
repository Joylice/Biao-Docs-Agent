<template>
  <div
    class="word-version"
    :class="{ 'word-version--dark': isDark }"
    role="complementary"
    aria-label="版本历史面板"
  >
    <div class="word-version__header">
      <span class="word-version__title">版本历史</span>
      <a-button
        size="small"
        type="text"
        @click="$emit('close')"
        aria-label="关闭版本历史面板"
      >
        <template #icon>
          <CloseOutlined />
        </template>
      </a-button>
    </div>

    <!-- 工具栏 -->
    <div class="word-version__toolbar">
      <a-button
        size="small"
        type="primary"
        @click="showSaveModal = true"
      >
        <template #icon>
          <SaveOutlined />
        </template>
        保存版本
      </a-button>
      <a-button
        size="small"
        @click="showCompare = !showCompare"
        :type="showCompare ? 'primary' : 'default'"
      >
        <template #icon>
          <DiffOutlined />
        </template>
        对比
      </a-button>
    </div>

    <!-- 对比视图 -->
    <div v-if="showCompare && selectedVersion" class="word-version__compare">
      <div class="word-version__compare-header">
        <span>版本 #{{ selectedVersion.versionNumber }} 与当前内容对比</span>
        <a-button size="small" type="text" @click="showCompare = false">
          <CloseOutlined />
        </a-button>
      </div>
      <div class="word-version__diff">
        <div
          v-for="(seg, idx) in diffSegments"
          :key="idx"
          class="word-version__diff-line"
          :class="{
            'word-version__diff-line--add': seg.type === 'add',
            'word-version__diff-line--remove': seg.type === 'remove',
          }"
        >
          <span class="word-version__diff-sign">
            {{ seg.type === 'add' ? '+' : seg.type === 'remove' ? '-' : ' ' }}
          </span>
          <span class="word-version__diff-text">{{ seg.text || '&nbsp;' }}</span>
        </div>
        <div v-if="diffSegments.length === 0" class="word-version__diff-empty">
          无差异
        </div>
      </div>
    </div>

    <!-- 版本列表 -->
    <div class="word-version__list">
      <div v-if="versions.length === 0" class="word-version__empty">
        <HistoryOutlined class="word-version__empty-icon" />
        <p>暂无版本记录</p>
        <p class="word-version__empty-hint">点击"保存版本"创建手动快照</p>
      </div>

      <div
        v-for="version in versions"
        :key="version.id"
        class="word-version__item"
        :class="{ 'word-version__item--active': selectedVersionId === version.id }"
        @click="selectVersion(version.id)"
      >
        <div class="word-version__item-header">
          <span class="word-version__version">
            <a-tag :color="version.isAuto ? 'default' : 'blue'" size="small">
              v{{ version.versionNumber }}
            </a-tag>
            <a-tag v-if="version.isAuto" color="default" size="small">自动</a-tag>
          </span>
          <span class="word-version__time">{{ formatTime(version.createdAt) }}</span>
        </div>

        <div v-if="version.note" class="word-version__note">{{ version.note }}</div>

        <div class="word-version__meta">
          <span>{{ version.author }}</span>
          <span>{{ version.wordCount }} 字</span>
        </div>

        <!-- 操作按钮 -->
        <div class="word-version__actions" @click.stop>
          <a-button
            size="small"
            type="primary"
            @click="restoreVersion(version.id)"
          >
            <template #icon><RollbackOutlined /></template>
            恢复
          </a-button>
          <a-button
            size="small"
            @click="compareWithCurrent(version.id)"
          >
            <template #icon><DiffOutlined /></template>
            对比
          </a-button>
          <a-popconfirm
            title="确定删除此版本？"
            @confirm="deleteVersion(version.id)"
          >
            <a-button size="small" danger type="text">
              <template #icon><DeleteOutlined /></template>
            </a-button>
          </a-popconfirm>
        </div>
      </div>
    </div>

    <!-- 保存版本弹窗 -->
    <a-modal
      v-model:open="showSaveModal"
      title="保存版本"
      ok-text="保存"
      cancel-text="取消"
      @ok="handleSaveVersion"
    >
      <a-textarea
        v-model:value="newVersionNote"
        :rows="3"
        placeholder="输入版本备注（可选），如：完成技术架构章节"
      />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorVersionHistory：版本历史面板
 * - 显示版本列表（手动/自动）
 * - 手动保存版本
 * - 版本对比（与当前内容差异高亮）
 * - 版本恢复
 * - 删除版本
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  CloseOutlined,
  SaveOutlined,
  DiffOutlined,
  HistoryOutlined,
  RollbackOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import { useVersionHistory, type DiffSegment } from '@/composables/useVersionHistory'
import { htmlToMarkdown } from '@/utils/markdown-converter'

const props = defineProps<{
  editor?: Editor
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'restore', content: string): void
}>()

/* 深色模式 */
const isDark = ref(false)
const checkDarkMode = () => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
}
let darkObserver: MutationObserver | null = null

/* 版本历史管理 */
const {
  versions,
  selectedVersionId,
  saveVersion,
  getVersion,
  deleteVersion,
  compareWithCurrent: doCompare,
  formatTime,
} = useVersionHistory()

/* 保存版本弹窗 */
const showSaveModal = ref(false)
const newVersionNote = ref('')

/* 对比视图 */
const showCompare = ref(false)
const diffSegments = ref<DiffSegment[]>([])

/* 选中的版本 */
const selectedVersion = computed(() => {
  if (!selectedVersionId.value) return null
  return getVersion(selectedVersionId.value)
})

/**
 * 保存版本
 */
const handleSaveVersion = () => {
  const ed = props.editor
  if (!ed) return
  const html = ed.getHTML()
  const markdown = htmlToMarkdown(html)
  saveVersion(html, { note: newVersionNote.value || undefined, markdown, isAuto: false })
  newVersionNote.value = ''
  showSaveModal.value = false
}

/**
 * 选中版本
 */
const selectVersion = (id: string) => {
  selectedVersionId.value = selectedVersionId.value === id ? null : id
  if (showCompare.value && selectedVersionId.value) {
    doCompareWithCurrent(id)
  }
}

/**
 * 与当前内容对比
 */
const doCompareWithCurrent = (id: string) => {
  const ed = props.editor
  if (!ed) return
  const currentHtml = ed.getHTML()
  diffSegments.value = doCompare(id, currentHtml)
  showCompare.value = true
  selectedVersionId.value = id
}

const compareWithCurrent = (id: string) => {
  doCompareWithCurrent(id)
}

/**
 * 恢复版本
 */
const restoreVersion = (id: string) => {
  const version = getVersion(id)
  if (!version) return
  if (confirm(`确定恢复到版本 #${version.versionNumber}？当前内容将被替换。`)) {
    emit('restore', version.content)
  }
}

/* 监听对比视图开关 */
watch(showCompare, (val) => {
  if (val && selectedVersionId.value) {
    doCompareWithCurrent(selectedVersionId.value)
  }
})

/* 生命周期 */
onMounted(() => {
  checkDarkMode()
  darkObserver = new MutationObserver(checkDarkMode)
  darkObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onBeforeUnmount(() => {
  darkObserver?.disconnect()
})
</script>

<style scoped>
.word-version {
  width: 340px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-color);
  font-size: var(--font-size-sm);
}

.word-version__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.word-version__title {
  font-weight: 600;
  color: var(--text-primary);
}

.word-version__toolbar {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.word-version__compare {
  max-height: 300px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
}

.word-version__compare-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface-active);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.word-version__diff {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: var(--font-size-xs);
}

.word-version__diff-line {
  display: flex;
  gap: var(--space-2);
  padding: 1px 4px;
  white-space: pre-wrap;
  word-break: break-all;
}

.word-version__diff-line--add {
  background: rgba(82, 196, 26, 0.1);
  color: var(--color-success);
}

.word-version__diff-line--remove {
  background: rgba(245, 34, 45, 0.1);
  color: var(--color-error);
  text-decoration: line-through;
}

.word-version__diff-sign {
  flex-shrink: 0;
  width: 12px;
  font-weight: bold;
}

.word-version__diff-text {
  flex: 1;
}

.word-version__diff-empty {
  text-align: center;
  color: var(--text-tertiary);
  padding: var(--space-4);
}

.word-version__list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.word-version__empty {
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--text-tertiary);
}
.word-version__empty-icon {
  font-size: 32px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}
.word-version__empty p {
  margin: var(--space-1) 0;
}
.word-version__empty-hint {
  font-size: var(--font-size-xs);
  opacity: 0.7;
}

.word-version__item {
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  background: var(--bg-surface-active);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}
.word-version__item:hover {
  border-color: var(--color-primary);
}
.word-version__item--active {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-light);
}

.word-version__item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1);
}

.word-version__version {
  display: flex;
  gap: var(--space-1);
}

.word-version__time {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.word-version__note {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  margin-bottom: var(--space-1);
  line-height: 1.4;
}

.word-version__meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin-bottom: var(--space-2);
}

.word-version__actions {
  display: flex;
  gap: var(--space-2);
}
</style>
