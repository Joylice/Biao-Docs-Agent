<template>
  <div class="word-statusbar">
    <div class="word-statusbar__counts">
      <span>{{ words }} 字</span>
      <a-divider type="vertical" />
      <span>{{ characters }} 字符</span>
    </div>
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
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorStatusBar：字数/字符数统计 + 保存状态展示（P0 简化版）
 * 统计基于 character-count 扩展存储，随事务版本号刷新。
 */
import { computed, ref, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  LoadingOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloudOutlined,
} from '@ant-design/icons-vue'

/** 保存状态机（与 WordEditorPage 保持一致） */
export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 当前保存状态 */
  saveStatus: SaveStatus
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

/** 字符数（character-count 扩展） */
const characters = computed(() => {
  void version.value
  return (props.editor?.storage.characterCount?.characters() as number | undefined) ?? 0
})

/** 字数（按空白分词统计） */
const words = computed(() => {
  void version.value
  return (props.editor?.storage.characterCount?.words() as number | undefined) ?? 0
})

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
}

.word-statusbar__counts {
  display: flex;
  align-items: center;
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
</style>
