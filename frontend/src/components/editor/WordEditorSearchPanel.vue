<template>
  <div
    v-if="visible"
    class="word-search-panel"
    role="dialog"
    aria-label="查找替换"
  >
    <div class="word-search-panel__row">
      <a-input
        v-model:value="query"
        size="small"
        placeholder="查找内容"
        allow-clear
        aria-label="查找内容"
        class="word-search-panel__input"
        @keydown.enter.prevent="onEnter"
      >
        <template #prefix>
          <SearchOutlined />
        </template>
      </a-input>
      <span
        class="word-search-panel__count"
        :class="{ 'is-empty': matchCount === 0 }"
      >
        {{ countText }}
      </span>
      <a-tooltip title="上一个">
        <a-button
          size="small"
          type="text"
          :disabled="matchCount === 0"
          aria-label="上一个匹配"
          @click="prev"
        >
          <template #icon>
            <ArrowUpOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="下一个">
        <a-button
          size="small"
          type="text"
          :disabled="matchCount === 0"
          aria-label="下一个匹配"
          @click="next"
        >
          <template #icon>
            <ArrowDownOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="关闭">
        <a-button
          size="small"
          type="text"
          aria-label="关闭查找替换"
          @click="close"
        >
          <template #icon>
            <CloseOutlined />
          </template>
        </a-button>
      </a-tooltip>
    </div>

    <div
      v-if="mode === 'replace'"
      class="word-search-panel__row"
    >
      <a-input
        v-model:value="replacement"
        size="small"
        placeholder="替换为"
        allow-clear
        aria-label="替换内容"
        class="word-search-panel__input"
      />
      <a-button
        size="small"
        :disabled="matchCount === 0"
        @click="replaceOne"
      >
        替换
      </a-button>
      <a-button
        size="small"
        :disabled="matchCount === 0"
        @click="replaceAll"
      >
        全部替换
      </a-button>
    </div>

    <div class="word-search-panel__options">
      <a-checkbox v-model:checked="caseSensitive">
        区分大小写
      </a-checkbox>
      <a-checkbox v-model:checked="wholeWord">
        全字匹配
      </a-checkbox>
      <a-checkbox v-model:checked="useRegex">
        正则表达式
      </a-checkbox>
      <a-button
        v-if="mode === 'find'"
        size="small"
        type="link"
        @click="switchToReplace"
      >
        展开替换
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorSearchPanel：查找替换浮层面板。
 * - 内部使用 useSearchReplace composable（ProseMirror Plugin + Decoration 高亮）。
 * - v-model:visible 控制显隐；mode: 'find' 仅查找 / 'replace' 含替换。
 * - 定位在编辑区右上角（fixed），深色模式自适应。
 * - Enter 跳转下一个匹配；Esc 关闭面板。
 */
import { computed, toRef, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  SearchOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  CloseOutlined,
} from '@ant-design/icons-vue'
import { useSearchReplace } from '@/composables/useSearchReplace'

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 是否显示 */
  visible: boolean
  /** 模式：仅查找 / 含替换 */
  mode?: 'find' | 'replace'
  /** 初始查询词（右键菜单"查找选中文字"传入） */
  initialQuery?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update:mode', value: 'find' | 'replace'): void
}>()

// 将 editor prop 转为响应式引用供 composable 使用
const editorRef = toRef(props, 'editor')
const {
  query,
  replacement,
  caseSensitive,
  wholeWord,
  useRegex,
  matches,
  currentIndex,
  search,
  next,
  prev,
  replaceOne,
  replaceAll,
  clear,
} = useSearchReplace(editorRef)

/** initialQuery 变化 → 同步到搜索框并触发搜索（右键菜单查找选中文字） */
watch(
  () => props.initialQuery,
  (q) => {
    if (q) {
      query.value = q
      search()
    }
  },
)

const mode = computed(() => props.mode ?? 'find')

const matchCount = computed(() => matches.value.length)

const countText = computed(() => {
  if (matchCount.value === 0) return query.value ? '无匹配' : ''
  return `第 ${currentIndex.value + 1} / ${matchCount.value} 个`
})

const onEnter = () => {
  if (matchCount.value > 0) {
    next()
  } else {
    search()
  }
}

const close = () => {
  clear()
  emit('update:visible', false)
}

const switchToReplace = () => {
  emit('update:mode', 'replace')
}
</script>

<style scoped>
.word-search-panel {
  position: fixed;
  top: 88px;
  right: 24px;
  z-index: 1000;
  width: 320px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.word-search-panel__row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.word-search-panel__input {
  flex: 1;
  min-width: 0;
}

.word-search-panel__count {
  flex: 0 0 auto;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  white-space: nowrap;
}
.word-search-panel__count.is-empty {
  color: var(--text-tertiary);
}

.word-search-panel__options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
  font-size: var(--font-size-xs);
}
</style>

<!-- 查找高亮装饰样式（编辑区 :deep 无法覆盖 ProseMirror 装饰节点，需全局样式） -->
<style>
/* 普通匹配：浅黄底 */
.word-editor__prosemirror .search-match {
  background: rgba(250, 204, 21, 0.35);
  border-radius: 2px;
  box-shadow: 0 0 0 1px rgba(250, 204, 21, 0.3);
}
/* 当前匹配：主色描边 */
.word-editor__prosemirror .search-match--current {
  background: rgba(59, 130, 246, 0.25);
  box-shadow: 0 0 0 2px var(--color-primary);
}
</style>
