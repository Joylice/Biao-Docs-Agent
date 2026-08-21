<template>
  <div
    class="word-toolbar"
    role="toolbar"
    aria-label="编辑器格式工具栏"
  >
    <a-space
      wrap
      :size="2"
      class="word-toolbar__group"
    >
      <!-- 撤销 / 重做 -->
      <a-tooltip title="撤销 (Ctrl+Z)">
        <a-button
          size="small"
          type="text"
          :disabled="!canUndo"
          aria-label="撤销"
          @click="run((chain) => chain.undo())"
        >
          <template #icon>
            <UndoOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="重做 (Ctrl+Y)">
        <a-button
          size="small"
          type="text"
          :disabled="!canRedo"
          aria-label="重做"
          @click="run((chain) => chain.redo())"
        >
          <template #icon>
            <RedoOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 段落格式：正文 / H1-H4 -->
      <a-select
        :value="paragraphValue"
        size="small"
        class="word-toolbar__select word-toolbar__select--paragraph"
        aria-label="段落格式"
        :options="paragraphOptions"
        @change="handleParagraphChange"
      />

      <!-- 字体 -->
      <a-select
        :value="currentFontFamily"
        size="small"
        class="word-toolbar__select word-toolbar__select--font"
        aria-label="字体"
        placeholder="字体"
        :options="fontFamilyOptions"
        @change="handleFontFamilyChange"
      />

      <!-- 字号（中文字号映射） -->
      <a-select
        :value="currentFontSize"
        size="small"
        class="word-toolbar__select word-toolbar__select--size"
        aria-label="字号"
        placeholder="字号"
        :options="fontSizeOptions"
        @change="handleFontSizeChange"
      />

      <!-- 行高 -->
      <a-select
        :value="currentLineHeight"
        size="small"
        class="word-toolbar__select word-toolbar__select--line-height"
        aria-label="行高"
        placeholder="行高"
        :options="lineHeightOptions"
        @change="handleLineHeightChange"
      />

      <a-divider type="vertical" />

      <!-- 加粗 / 斜体 / 下划线 / 删除线 -->
      <a-tooltip title="加粗 (Ctrl+B)">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('bold') }"
          aria-label="加粗"
          @click="run((chain) => chain.toggleBold())"
        >
          <template #icon>
            <BoldOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="斜体 (Ctrl+I)">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('italic') }"
          aria-label="斜体"
          @click="run((chain) => chain.toggleItalic())"
        >
          <template #icon>
            <ItalicOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="下划线 (Ctrl+U)">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('underline') }"
          aria-label="下划线"
          @click="run((chain) => chain.toggleUnderline())"
        >
          <template #icon>
            <UnderlineOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="删除线">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('strike') }"
          aria-label="删除线"
          @click="run((chain) => chain.toggleStrike())"
        >
          <template #icon>
            <StrikethroughOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <!-- 文字颜色 -->
      <a-popover
        trigger="click"
        placement="bottom"
        overlay-class-name="word-toolbar-popover"
      >
        <template #content>
          <div class="word-toolbar__palette">
            <button
              v-for="color in TEXT_COLOR_PRESETS"
              :key="color"
              type="button"
              class="word-toolbar__swatch"
              :style="{ background: color }"
              :aria-label="`文字颜色 ${color}`"
              @click="handleTextColor(color)"
            />
            <button
              type="button"
              class="word-toolbar__swatch-reset"
              aria-label="清除文字颜色"
              @click="run((chain) => chain.unsetColor())"
            >
              默认
            </button>
          </div>
        </template>
        <a-button
          size="small"
          type="text"
          aria-label="文字颜色"
        >
          <template #icon>
            <BgColorsOutlined />
          </template>
        </a-button>
      </a-popover>

      <!-- 高亮颜色 -->
      <a-popover
        trigger="click"
        placement="bottom"
        overlay-class-name="word-toolbar-popover"
      >
        <template #content>
          <div class="word-toolbar__palette">
            <button
              v-for="color in HIGHLIGHT_COLOR_PRESETS"
              :key="color"
              type="button"
              class="word-toolbar__swatch"
              :style="{ background: color }"
              :aria-label="`高亮颜色 ${color}`"
              @click="handleHighlight(color)"
            />
            <button
              type="button"
              class="word-toolbar__swatch-reset"
              aria-label="清除高亮"
              @click="run((chain) => chain.unsetHighlight())"
            >
              无
            </button>
          </div>
        </template>
        <a-button
          size="small"
          type="text"
          aria-label="高亮颜色"
        >
          <template #icon>
            <HighlightOutlined />
          </template>
        </a-button>
      </a-popover>

      <a-divider type="vertical" />

      <!-- 对齐：左 / 中 / 右 / 两端 -->
      <a-tooltip title="左对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive({ textAlign: 'left' }) }"
          aria-label="左对齐"
          @click="run((chain) => chain.setTextAlign('left'))"
        >
          <template #icon>
            <AlignLeftOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="居中对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive({ textAlign: 'center' }) }"
          aria-label="居中对齐"
          @click="run((chain) => chain.setTextAlign('center'))"
        >
          <template #icon>
            <AlignCenterOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="右对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive({ textAlign: 'right' }) }"
          aria-label="右对齐"
          @click="run((chain) => chain.setTextAlign('right'))"
        >
          <template #icon>
            <AlignRightOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="两端对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive({ textAlign: 'justify' }) }"
          aria-label="两端对齐"
          @click="run((chain) => chain.setTextAlign('justify'))"
        >
          <template #icon>
            <MenuOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 列表：无序 / 有序 / 任务 -->
      <a-tooltip title="无序列表">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('bulletList') }"
          aria-label="无序列表"
          @click="run((chain) => chain.toggleBulletList())"
        >
          <template #icon>
            <UnorderedListOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="有序列表">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('orderedList') }"
          aria-label="有序列表"
          @click="run((chain) => chain.toggleOrderedList())"
        >
          <template #icon>
            <OrderedListOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="任务列表">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-toolbar__btn--active': isActive('taskList') }"
          aria-label="任务列表"
          @click="run((chain) => chain.toggleTaskList())"
        >
          <template #icon>
            <CheckSquareOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 缩进：减少 / 增加（text-indent 步进 2em） -->
      <a-tooltip title="减少缩进">
        <a-button
          size="small"
          type="text"
          aria-label="减少缩进"
          @click="run((chain) => chain.decreaseIndent())"
        >
          <template #icon>
            <MenuFoldOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="增加缩进">
        <a-button
          size="small"
          type="text"
          aria-label="增加缩进"
          @click="run((chain) => chain.increaseIndent())"
        >
          <template #icon>
            <MenuUnfoldOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 清除格式 -->
      <a-tooltip title="清除格式">
        <a-button
          size="small"
          type="text"
          aria-label="清除格式"
          @click="handleClearFormat"
        >
          <template #icon>
            <ClearOutlined />
          </template>
        </a-button>
      </a-tooltip>
    </a-space>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorToolbar：「开始」选项卡工具栏
 * 通过 editor 实例驱动命令，借助 transaction 版本号强制同步按钮 active 状态。
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import type { Editor, ChainedCommands } from '@tiptap/core'
import {
  UndoOutlined,
  RedoOutlined,
  BoldOutlined,
  ItalicOutlined,
  UnderlineOutlined,
  StrikethroughOutlined,
  BgColorsOutlined,
  HighlightOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
  MenuOutlined,
  UnorderedListOutlined,
  OrderedListOutlined,
  CheckSquareOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ClearOutlined,
} from '@ant-design/icons-vue'
import { FONT_FAMILY_OPTIONS } from './extensions/font-family'
import { FONT_SIZE_OPTIONS } from './extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from './extensions/line-height'
import { TEXT_COLOR_PRESETS } from './extensions/text-color'
import { HIGHLIGHT_COLOR_PRESETS } from './extensions/highlight'

const props = defineProps<{
  /** 编辑器实例（由父组件传入；未就绪时为 undefined） */
  editor: Editor | undefined
}>()

/* 事务版本号：editor 状态变化时递增，使 computed/渲染依赖重新求值 */
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

onBeforeUnmount(() => {
  props.editor?.off('transaction', bump)
})

/** 执行一条链式命令（统一 focus，保证编辑区获得焦点） */
const run = (apply: (chain: ChainedCommands) => ChainedCommands) => {
  const editor = props.editor
  if (!editor) return
  apply(editor.chain().focus()).run()
}

/** 判断节点/mark 激活态；attrs 传入时按属性匹配（如 textAlign） */
const isActive = (nameOrAttrs: string | Record<string, unknown>): boolean => {
  // 读取 version 建立响应式依赖，保证状态同步
  void version.value
  const editor = props.editor
  if (!editor) return false
  return typeof nameOrAttrs === 'string'
    ? editor.isActive(nameOrAttrs)
    : editor.isActive(nameOrAttrs)
}

const canUndo = computed(() => {
  void version.value
  return props.editor?.can().undo() ?? false
})
const canRedo = computed(() => {
  void version.value
  return props.editor?.can().redo() ?? false
})

/* ---------------- 段落格式（正文 / H1-H4） ---------------- */
const paragraphOptions = [
  { label: '正文', value: 'paragraph' },
  { label: '标题 1', value: 'heading-1' },
  { label: '标题 2', value: 'heading-2' },
  { label: '标题 3', value: 'heading-3' },
  { label: '标题 4', value: 'heading-4' },
]

const paragraphValue = computed(() => {
  void version.value
  const editor = props.editor
  if (!editor) return 'paragraph'
  for (const level of [1, 2, 3, 4]) {
    if (editor.isActive('heading', { level })) return `heading-${level}`
  }
  return 'paragraph'
})

const handleParagraphChange = (value: string) => {
  if (value === 'paragraph') {
    run((chain) => chain.setParagraph())
  } else {
    const level = Number(value.split('-')[1]) as 1 | 2 | 3 | 4
    run((chain) => chain.setHeading({ level }))
  }
}

/* ---------------- 字体 / 字号 / 行高 ---------------- */
const fontFamilyOptions = FONT_FAMILY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
const fontSizeOptions = FONT_SIZE_OPTIONS.map((o) => ({ label: `${o.label} · ${o.value}`, value: o.value }))
const lineHeightOptions = LINE_HEIGHT_OPTIONS.map((v) => ({ label: `行高 ${v}`, value: String(v) }))

const textStyleAttrs = computed<Record<string, unknown>>(() => {
  void version.value
  return props.editor?.getAttributes('textStyle') ?? {}
})

const currentFontFamily = computed(() => (textStyleAttrs.value.fontFamily as string) ?? undefined)
const currentFontSize = computed(() => (textStyleAttrs.value.fontSize as string) ?? undefined)

const currentLineHeight = computed(() => {
  void version.value
  const editor = props.editor
  if (!editor) return undefined
  // 行高挂在块级节点上：优先取标题，其次段落
  const attrs = editor.isActive('heading')
    ? editor.getAttributes('heading')
    : editor.getAttributes('paragraph')
  return (attrs.lineHeight as string | undefined) ?? undefined
})

const handleFontFamilyChange = (value: string) => {
  run((chain) => chain.setFontFamily(value))
}

const handleFontSizeChange = (value: string) => {
  run((chain) => chain.setFontSize(value))
}

const handleLineHeightChange = (value: string) => {
  run((chain) => chain.setLineHeight(value))
}

/* ---------------- 颜色 / 高亮 ---------------- */
const handleTextColor = (color: string) => {
  run((chain) => chain.setColor(color))
}

const handleHighlight = (color: string) => {
  run((chain) => chain.setHighlight({ color }))
}

/* ---------------- 清除格式 ---------------- */
const handleClearFormat = () => {
  run((chain) => chain.clearNodes().unsetAllMarks())
}
</script>

<style scoped>
.word-toolbar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
  padding: var(--space-1) var(--space-3);
}

.word-toolbar__group {
  width: 100%;
}

.word-toolbar__select {
  min-width: 88px;
}
.word-toolbar__select--paragraph {
  min-width: 96px;
}
.word-toolbar__select--font {
  min-width: 132px;
}
.word-toolbar__select--size {
  min-width: 104px;
}
.word-toolbar__select--line-height {
  min-width: 88px;
}

/* 激活态按钮：主色 + 主色浅底（走主题变量，深浅色自适应） */
.word-toolbar__btn--active {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

/* 色板弹层：网格排布 */
.word-toolbar__palette {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
  align-items: center;
}

.word-toolbar__swatch {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-color);
  cursor: pointer;
  padding: 0;
  transition: transform var(--transition-fast);
}
.word-toolbar__swatch:hover {
  transform: scale(1.12);
}

.word-toolbar__swatch-reset {
  grid-column: span 4;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  padding: 3px 0;
  cursor: pointer;
}
.word-toolbar__swatch-reset:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}
</style>

<!-- 色板弹层渲染在 body 下（teleport），需非 scoped 样式覆盖深色适配 -->
<style>
.word-toolbar-popover .ant-popover-inner {
  background: var(--bg-elevated);
}
</style>