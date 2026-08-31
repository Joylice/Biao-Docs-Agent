<template>
  <a-space
    wrap
    :size="2"
    class="word-toolbar__group"
  >
    <!-- 页边距 -->
    <span class="word-toolbar__label">页边距</span>
    <a-select
      v-model:value="pageMargin"
      size="small"
      class="word-toolbar__select"
      :options="pageMarginOptions"
    />

    <a-divider type="vertical" />

    <!-- 纸张方向 -->
    <span class="word-toolbar__label">方向</span>
    <a-button-group>
      <a-button
        size="small"
        :type="paperOrientation === 'portrait' ? 'primary' : 'default'"
        @click="paperOrientation = 'portrait'"
      >
        纵向
      </a-button>
      <a-button
        size="small"
        :type="paperOrientation === 'landscape' ? 'primary' : 'default'"
        @click="paperOrientation = 'landscape'"
      >
        横向
      </a-button>
    </a-button-group>

    <a-divider type="vertical" />

    <!-- 纸张大小 -->
    <span class="word-toolbar__label">纸张</span>
    <a-select
      v-model:value="paperSize"
      size="small"
      class="word-toolbar__select"
      :options="paperSizeOptions"
    />

    <a-divider type="vertical" />

    <!-- 分栏（P2） -->
    <a-tooltip title="P2 实现">
      <a-button
        size="small"
        type="text"
        disabled
      >
        分栏
      </a-button>
    </a-tooltip>

    <a-divider type="vertical" />

    <!-- 缩进 -->
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

    <!-- 行距 -->
    <span class="word-toolbar__label">行距</span>
    <a-select
      :value="currentLineHeight"
      size="small"
      class="word-toolbar__select word-toolbar__select--line-height"
      :options="lineHeightOptions"
      @change="handleLineHeightChange"
    />
  </a-space>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import type { Editor } from '@tiptap/core'
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
import { useEditorCommands } from './useEditorCommands'

const props = defineProps<{
  editor: Editor | undefined
}>()

const { run, currentLineHeight, lineHeightOptions, handleLineHeightChange } = useEditorCommands(
  () => props.editor,
)

/* 页边距：通过 CSS 变量 --paper-padding 控制纸面 padding */
const pageMargin = ref('moderate')
const pageMarginOptions = [
  { label: '窄', value: 'narrow' },
  { label: '适中', value: 'moderate' },
  { label: '宽', value: 'wide' },
  { label: '自定义', value: 'custom' },
]
const PAGE_MARGIN_MAP: Record<string, string> = {
  narrow: '12.7mm',
  moderate: '25.4mm',
  wide: '38.1mm',
  custom: '25.4mm',
}
watch(pageMargin, (val) => {
  document.documentElement.style.setProperty('--paper-padding', PAGE_MARGIN_MAP[val] ?? '25.4mm')
})

/* 纸张方向：通过 CSS 变量切换纸面宽高 */
const paperOrientation = ref<'portrait' | 'landscape'>('portrait')
const PAPER_DIMENSIONS: Record<string, [string, string]> = {
  A4: ['210mm', '297mm'],
  Letter: ['216mm', '279mm'],
  custom: ['210mm', '297mm'],
}

/* 纸张大小 */
const paperSize = ref('A4')
const paperSizeOptions = [
  { label: 'A4', value: 'A4' },
  { label: 'Letter', value: 'Letter' },
  { label: '自定义', value: 'custom' },
]

const applyPaperDimensions = () => {
  const [w, h] = PAPER_DIMENSIONS[paperSize.value] ?? PAPER_DIMENSIONS.A4
  if (paperOrientation.value === 'landscape') {
    document.documentElement.style.setProperty('--paper-width', h)
    document.documentElement.style.setProperty('--paper-height', w)
  } else {
    document.documentElement.style.setProperty('--paper-width', w)
    document.documentElement.style.setProperty('--paper-height', h)
  }
  document.documentElement.setAttribute('data-paper-orientation', paperOrientation.value)
  document.documentElement.setAttribute('data-paper-size', paperSize.value)
}

watch(paperOrientation, applyPaperDimensions)
watch(paperSize, applyPaperDimensions)

onBeforeUnmount(() => {
  document.documentElement.style.removeProperty('--paper-padding')
  document.documentElement.style.removeProperty('--paper-width')
  document.documentElement.style.removeProperty('--paper-height')
  document.documentElement.removeAttribute('data-paper-orientation')
  document.documentElement.removeAttribute('data-paper-size')
})
</script>

<style scoped>
.word-toolbar__group {
  width: 100%;
}

.word-toolbar__label {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.word-toolbar__select {
  min-width: 88px;
}
.word-toolbar__select--line-height {
  min-width: 96px;
}
</style>
