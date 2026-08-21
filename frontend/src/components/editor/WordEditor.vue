<template>
  <div class="word-editor">
    <div class="word-editor__scroll">
      <!-- A4 纸面：宽 210mm、最小高 297mm、页边距 25.4mm -->
      <div class="word-editor__paper">
        <EditorContent
          :editor="editor"
          class="word-editor__content"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditor：类 Word 富文本编辑区
 * - 外层灰色滚动区 + 居中 A4 白纸（深色模式下纸面强制白色，见样式注释）
 * - props：content(HTML)/readonly/placeholder；emit update:content
 * - defineExpose：getHTML/getJSON/getText/setContent/focus/editor
 */
import { watch } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import { createEditorExtensions } from './extensions'

interface WordEditorProps {
  /** 初始内容（HTML 字符串）；外部变化时编辑器同步刷新 */
  content?: string
  /** 只读模式（禁止编辑） */
  readonly?: boolean
  /** 空文档占位提示文案 */
  placeholder?: string
}

const props = withDefaults(defineProps<WordEditorProps>(), {
  content: '',
  readonly: false,
  placeholder: '请输入内容...',
})

const emit = defineEmits<{
  (e: 'update:content', value: string): void
}>()

const editor = useEditor({
  extensions: createEditorExtensions({ placeholder: props.placeholder }),
  content: props.content,
  editable: !props.readonly,
  editorProps: {
    attributes: {
      class: 'word-editor__prosemirror',
      'aria-label': '富文本编辑区',
    },
  },
  onUpdate: ({ editor: instance }) => {
    emit('update:content', instance.getHTML())
  },
})

// readonly 变化 → 同步编辑器可编辑状态
watch(
  () => props.readonly,
  (readonly) => {
    editor.value?.setEditable(!readonly)
  },
)

// 外部 content 变化 → 重置内容（内容一致时跳过，避免光标跳动）
watch(
  () => props.content,
  (content) => {
    const instance = editor.value
    if (!instance || instance.getHTML() === content) return
    instance.commands.setContent(content, false)
  },
)

/** 获取当前 HTML */
const getHTML = (): string => editor.value?.getHTML() ?? ''
/** 获取当前文档 JSON */
const getJSON = (): Record<string, unknown> => editor.value?.getJSON() ?? {}
/** 获取当前纯文本 */
const getText = (): string => editor.value?.getText() ?? ''
/** 外部设置内容（会进入撤销历史） */
const setContent = (content: string): void => {
  editor.value?.commands.setContent(content)
}
/** 聚焦编辑区 */
const focus = (): void => {
  editor.value?.commands.focus()
}

defineExpose({ editor, getHTML, getJSON, getText, setContent, focus })
</script>

<style scoped>
.word-editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 外层滚动区：灰色背景（走主题变量），纸面水平居中 */
.word-editor__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: var(--bg-app);
  padding: var(--space-6) var(--space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* A4 纸面：210mm × ≥297mm，页边距 25.4mm（1 英寸）
   注意：纸面底色/文字色刻意使用字面量而非主题变量——
   深色模式下纸张必须保持白色、文字保持深色，以模拟真实纸张
   并保证与 Word 导出效果一致。 */
.word-editor__paper {
  width: 210mm;
  min-height: 297mm;
  padding: 25.4mm;
  box-sizing: border-box;
  background: #ffffff; /* 纸面恒白，不随主题变化 */
  color: #1f2329; /* 纸面文字恒深色，保证白纸可读性 */
  box-shadow: var(--shadow-md);
}

.word-editor__content {
  width: 100%;
}

/* ---------- ProseMirror 编辑区基础排版 ---------- */
.word-editor :deep(.word-editor__prosemirror) {
  outline: none;
  min-height: 246mm; /* 297mm - 2 × 25.4mm 页边距 */
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
  white-space: pre-wrap;
}

.word-editor :deep(.word-editor__prosemirror > * + *) {
  margin-top: 0.6em;
}

/* 标题 */
.word-editor :deep(.word-editor__prosemirror h1) {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.4;
  margin: 1em 0 0.6em;
}
.word-editor :deep(.word-editor__prosemirror h2) {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.4;
  margin: 0.9em 0 0.5em;
}
.word-editor :deep(.word-editor__prosemirror h3) {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  margin: 0.8em 0 0.5em;
}
.word-editor :deep(.word-editor__prosemirror h4) {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
  margin: 0.8em 0 0.4em;
}

/* 列表 */
.word-editor :deep(.word-editor__prosemirror ul),
.word-editor :deep(.word-editor__prosemirror ol) {
  padding-left: 1.5em;
}
.word-editor :deep(.word-editor__prosemirror ul[data-type='taskList']) {
  list-style: none;
  padding-left: 0.25em;
}
.word-editor :deep(.word-editor__prosemirror ul[data-type='taskList'] li) {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.word-editor :deep(.word-editor__prosemirror ul[data-type='taskList'] li > label) {
  flex: 0 0 auto;
  margin-top: 0.35em;
  user-select: none;
}
.word-editor :deep(.word-editor__prosemirror ul[data-type='taskList'] li > div) {
  flex: 1;
}
/* 已完成任务项：弱化色 + 删除线（纸面内使用字面量） */
.word-editor :deep(.word-editor__prosemirror ul[data-type='taskList'] li[data-checked='true'] > div) {
  color: #8f959e;
  text-decoration: line-through;
}

/* 引用 */
.word-editor :deep(.word-editor__prosemirror blockquote) {
  border-left: 3px solid #dee0e3;
  margin-left: 0;
  padding-left: 12px;
  color: #646a73; /* 纸面次要文字色 */
}

/* 表格（内容可能来自 Markdown 导入） */
.word-editor :deep(.word-editor__prosemirror table) {
  border-collapse: collapse;
  table-layout: fixed;
  width: 100%;
  margin: 8px 0;
}
.word-editor :deep(.word-editor__prosemirror th),
.word-editor :deep(.word-editor__prosemirror td) {
  border: 1px solid #dee0e3;
  padding: 6px 8px;
  vertical-align: top;
  min-width: 1em;
}
.word-editor :deep(.word-editor__prosemirror th) {
  background: #f5f6f7; /* 纸面表头底色 */
  font-weight: 600;
}

/* 代码/分割线/图片/链接（纸面内样式，使用字面量） */
.word-editor :deep(.word-editor__prosemirror code) {
  background: #f5f6f7;
  border-radius: 3px;
  padding: 0.15em 0.35em;
  font-family: var(--font-family-mono);
  font-size: 0.9em;
}
.word-editor :deep(.word-editor__prosemirror pre) {
  background: #f5f6f7;
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
}
.word-editor :deep(.word-editor__prosemirror pre code) {
  background: none;
  padding: 0;
}
.word-editor :deep(.word-editor__prosemirror hr) {
  border: none;
  border-top: 1px solid #dee0e3;
  margin: 1em 0;
}
.word-editor :deep(.word-editor__prosemirror img) {
  max-width: 100%;
  height: auto;
}
.word-editor :deep(.word-editor__prosemirror a) {
  color: #3370ff;
  text-decoration: underline;
}

/* 选区高亮：纸面上使用半透明主色（字面量，深浅主题一致） */
.word-editor :deep(.word-editor__prosemirror ::selection) {
  background: rgba(59, 130, 246, 0.25);
}

/* 占位符（extension-placeholder 约定类名） */
.word-editor :deep(.word-editor__prosemirror p.is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
  color: #8f959e; /* 纸面占位文字色 */
}
</style>