<template>
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

    <!-- 格式刷 -->
    <a-tooltip title="单击复制格式，双击连续复制（Esc 取消）">
      <a-button
        size="small"
        type="text"
        :class="{ 'word-toolbar__btn--active': brushActive }"
        aria-label="格式刷"
        @click="handleBrushClick"
        @dblclick="handleBrushDblClick"
      >
        <template #icon>
          <FormatPainterOutlined />
        </template>
      </a-button>
    </a-tooltip>

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

    <!-- 缩进：减少 / 增加 -->
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
</template>

<script setup lang="ts">
import type { Editor } from '@tiptap/core'
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
  FormatPainterOutlined,
} from '@ant-design/icons-vue'
import { TEXT_COLOR_PRESETS } from '../extensions/text-color'
import { HIGHLIGHT_COLOR_PRESETS } from '../extensions/highlight'
import { useEditorCommands } from './useEditorCommands'

const props = defineProps<{
  editor: Editor | undefined
}>()

const {
  run,
  isActive,
  canUndo,
  canRedo,
  paragraphOptions,
  paragraphValue,
  handleParagraphChange,
  fontFamilyOptions,
  fontSizeOptions,
  lineHeightOptions,
  currentFontFamily,
  currentFontSize,
  currentLineHeight,
  handleFontFamilyChange,
  handleFontSizeChange,
  handleLineHeightChange,
  handleTextColor,
  handleHighlight,
  handleClearFormat,
  brushActive,
  handleBrushClick,
  handleBrushDblClick,
} = useEditorCommands(() => props.editor)
</script>

<style scoped>
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
  min-width: 96px;
}

.word-toolbar__btn--active {
  color: var(--primary-color, #1890ff) !important;
  background: rgba(24, 144, 255, 0.1) !important;
}

.word-toolbar__palette {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  padding: 8px;
}

.word-toolbar__swatch {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #444);
  cursor: pointer;
  padding: 0;
  transition: transform 0.15s;
}
.word-toolbar__swatch:hover {
  transform: scale(1.15);
}

.word-toolbar__swatch-reset {
  grid-column: span 6;
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid var(--border-color, #444);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary, #ccc);
  cursor: pointer;
}
.word-toolbar__swatch-reset:hover {
  background: var(--bg-surface-hover, #333);
}
</style>
