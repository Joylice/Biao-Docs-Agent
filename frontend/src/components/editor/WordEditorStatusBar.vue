<template>
  <div class="word-statusbar">
    <!-- 左侧：统计信息组 -->
    <div class="word-statusbar__counts">
      <a-tooltip title="字数（按空白分词统计）">
        <span>{{ words }} 字</span>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="字符数（含空格）">
        <span>{{ characters }} 字符</span>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="字符数（不含空格）">
        <span>{{ charactersNoSpace }} 字符（无空格）</span>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="段落数">
        <span>{{ paragraphCount }} 段</span>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="行数（估算）">
        <span>{{ lineCount }} 行</span>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="光标位置（行 / 列，近似值）">
        <span>第 {{ cursorRow }} 行，第 {{ cursorColumn }} 列</span>
      </a-tooltip>
    </div>

    <!-- 右侧：保存状态 + 缩放 + 视图切换 -->
    <div class="word-statusbar__right">
      <div
        class="word-statusbar__save"
        :class="`word-statusbar__save--${saveStatus}`"
      >
        <LoadingOutlined
          v-if="saveStatus === 'saving'"
          spin
        />
        <CheckCircleOutlined v-else-if="saveStatus === 'saved'" />
        <ExclamationCircleOutlined v-else-if="saveStatus === 'error'" />
        <CloudOutlined v-else />
        <span>{{ saveText }}</span>
      </div>

      <a-divider type="vertical" />

      <!-- 缩放滑块 -->
      <div class="word-statusbar__zoom">
        <a-tooltip title="缩小">
          <button
            type="button"
            class="word-statusbar__zoom-btn"
            aria-label="缩小"
            @click="handleZoomOut"
          >
            <ZoomOutOutlined />
          </button>
        </a-tooltip>
        <a-slider
          v-model:value="zoomComputed"
          :min="10"
          :max="500"
          :step="10"
          class="word-statusbar__zoom-slider"
        />
        <a-tooltip title="放大">
          <button
            type="button"
            class="word-statusbar__zoom-btn"
            aria-label="放大"
            @click="handleZoomIn"
          >
            <ZoomInOutlined />
          </button>
        </a-tooltip>
        <span class="word-statusbar__zoom-value">{{ zoomComputed }}%</span>
      </div>

      <a-divider type="vertical" />

      <!-- 视图切换 -->
      <a-button-group class="word-statusbar__view">
        <a-button
          size="small"
          type="primary"
          aria-label="页面视图"
        >
          页面
        </a-button>
        <a-tooltip title="P2 实现">
          <a-button
            size="small"
            disabled
            aria-label="大纲视图"
          >
            大纲
          </a-button>
        </a-tooltip>
      </a-button-group>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorStatusBar：底部状态栏
 * - 左侧：字数 / 字符数 / 字符数（无空格）/ 段落数 / 行数 / 光标位置
 * - 右侧：保存状态 / 缩放滑块 / 视图切换
 * - 统计基于 character-count 扩展 + ProseMirror doc，随事务版本号刷新。
 */
import { computed, ref, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  LoadingOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloudOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons-vue'
import type { SaveStatus } from '@/types/editor'

export type { SaveStatus }

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 当前保存状态 */
  saveStatus: SaveStatus
  /** 当前缩放百分比（默认 100） */
  zoom?: number
}>()

const emit = defineEmits<{
  (e: 'update:zoom', value: number): void
}>()

/* 事务版本号：编辑内容变化时递增，驱动统计值重新计算 */
const version = ref(0)
const bump = () => {
  version.value++
}

watch(
  () => props.editor,
  (editor, _old, onCleanup) => {
    if (!editor) return
    editor.on('transaction', bump)
    onCleanup(() => {
      editor.off('transaction', bump)
    })
  },
  { immediate: true },
)

/* ---------------- 缩放（v-model:zoom） ---------------- */
const zoomComputed = computed({
  get: () => props.zoom ?? 100,
  set: (val: number) => emit('update:zoom', val),
})

const handleZoomOut = () => {
  zoomComputed.value = Math.max(10, zoomComputed.value - 10)
}
const handleZoomIn = () => {
  zoomComputed.value = Math.min(500, zoomComputed.value + 10)
}

/* ---------------- 统计：字数 / 字符数 ---------------- */
/** 字符数（character-count 扩展，含空格） */
const characters = computed(() => {
  void version.value
  return (props.editor?.storage.characterCount?.characters() as number | undefined) ?? 0
})

/** 字数（按空白分词统计） */
const words = computed(() => {
  void version.value
  return (props.editor?.storage.characterCount?.words() as number | undefined) ?? 0
})

/** 字符数（不含空格） */
const charactersNoSpace = computed(() => {
  void version.value
  const inst = props.editor
  if (!inst) return 0
  return inst.getText().replace(/\s/g, '').length
})

/** 段落数（顶层节点数） */
const paragraphCount = computed(() => {
  void version.value
  const inst = props.editor
  if (!inst) return 0
  return inst.state.doc.childCount
})

/** 行数（近似：纸面编辑区 scrollHeight / 行高） */
const lineCount = computed(() => {
  void version.value
  const inst = props.editor
  if (!inst) return 0
  const dom = inst.view.dom as HTMLElement
  const lineHeightStr = getComputedStyle(dom).lineHeight
  const lineHeight = parseFloat(lineHeightStr) || 24.5
  return Math.max(1, Math.ceil(dom.scrollHeight / lineHeight))
})

/** 光标位置：行号（段落数近似）/ 列号（段内偏移近似） */
const cursorRow = computed(() => {
  void version.value
  const inst = props.editor
  if (!inst) return 1
  const $from = inst.state.selection.$from
  // index(0) = 顶层块在 doc 中的索引（0-based），+1 转为行号
  return $from.index(0) + 1
})

const cursorColumn = computed(() => {
  void version.value
  const inst = props.editor
  if (!inst) return 1
  const $from = inst.state.selection.$from
  // parentOffset = 光标在当前块内的偏移（0-based），+1 转为列号
  return $from.parentOffset + 1
})

/* ---------------- 保存状态 ---------------- */
/** 保存状态文案 */
const SAVE_TEXT: Record<SaveStatus, string> = {
  idle: '未保存',
  saving: '保存中...',
  saved: '已保存',
  error: '保存失败',
}
const saveText = computed(() => SAVE_TEXT[props.saveStatus])
</script>

<style scoped>
.word-statusbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 28px;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border-top: 1px solid var(--border-color);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  overflow: hidden;
}

/* 左侧统计组 */
.word-statusbar__counts {
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.word-statusbar__counts > span {
  cursor: default;
}

/* 右侧：保存 + 缩放 + 视图 */
.word-statusbar__right {
  display: flex;
  align-items: center;
  gap: 0;
  flex-shrink: 0;
}

.word-statusbar__save {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

/* 保存状态着色：语义色走主题变量 */
.word-statusbar__save--idle {
  color: var(--text-tertiary);
}
.word-statusbar__save--saving {
  color: var(--color-primary);
}
.word-statusbar__save--saved {
  color: var(--color-success);
}
.word-statusbar__save--error {
  color: var(--color-error);
}

/* 缩放控制组 */
.word-statusbar__zoom {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.word-statusbar__zoom-btn {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  color: var(--text-secondary);
  transition: color var(--transition-fast);
}
.word-statusbar__zoom-btn:hover {
  color: var(--color-primary);
}
/* 缩放滑块：紧凑宽度 */
.word-statusbar__zoom-slider {
  width: 100px;
  margin: 0;
}
.word-statusbar__zoom-slider :deep(.ant-slider-handle) {
  width: 12px;
  height: 12px;
}
.word-statusbar__zoom-slider :deep(.ant-slider-track) {
  height: 3px;
}
.word-statusbar__zoom-slider :deep(.ant-slider-rail) {
  height: 3px;
}
.word-statusbar__zoom-value {
  min-width: 40px;
  text-align: right;
  color: var(--text-secondary);
}

/* 视图切换按钮组 */
.word-statusbar__view :deep(.ant-btn) {
  font-size: var(--font-size-xs);
}
</style>
