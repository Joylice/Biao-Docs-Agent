<template>
  <div
    v-if="inTable"
    class="word-table-toolbar"
    role="toolbar"
    aria-label="表格工具栏"
  >
    <a-space
      wrap
      :size="2"
    >
      <!-- 行/列增删 -->
      <a-tooltip title="上方插入行">
        <a-button
          size="small"
          type="text"
          aria-label="上方插入行"
          @click="run((c) => c.addRowBefore())"
        >
          <template #icon>
            <BorderTopOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="下方插入行">
        <a-button
          size="small"
          type="text"
          aria-label="下方插入行"
          @click="run((c) => c.addRowAfter())"
        >
          <template #icon>
            <BorderBottomOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="左侧插入列">
        <a-button
          size="small"
          type="text"
          aria-label="左侧插入列"
          @click="run((c) => c.addColumnBefore())"
        >
          <template #icon>
            <BorderLeftOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="右侧插入列">
        <a-button
          size="small"
          type="text"
          aria-label="右侧插入列"
          @click="run((c) => c.addColumnAfter())"
        >
          <template #icon>
            <BorderRightOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-divider type="vertical" />
      <a-tooltip title="删除行">
        <a-button
          size="small"
          type="text"
          aria-label="删除行"
          @click="run((c) => c.deleteRow())"
        >
          <template #icon>
            <MinusOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="删除列">
        <a-button
          size="small"
          type="text"
          aria-label="删除列"
          @click="run((c) => c.deleteColumn())"
        >
          <template #icon>
            <MinusOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="删除表格">
        <a-button
          size="small"
          type="text"
          danger
          aria-label="删除表格"
          @click="run((c) => c.deleteTable())"
        >
          <template #icon>
            <DeleteOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 合并 / 拆分 -->
      <a-tooltip title="合并单元格">
        <a-button
          size="small"
          type="text"
          :disabled="!canMerge"
          aria-label="合并单元格"
          @click="run((c) => c.mergeCells())"
        >
          <template #icon>
            <ColumnHeightOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="拆分单元格">
        <a-button
          size="small"
          type="text"
          :disabled="!canSplit"
          aria-label="拆分单元格"
          @click="run((c) => c.splitCell())"
        >
          <template #icon>
            <ColumnWidthOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="切换表头行">
        <a-button
          size="small"
          type="text"
          aria-label="切换表头行"
          @click="run((c) => c.toggleHeaderRow())"
        >
          <template #icon>
            <BorderOuterOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 水平对齐 -->
      <a-tooltip title="左对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-table-toolbar__btn--active': cellTextAlign === 'left' }"
          aria-label="单元格左对齐"
          @click="run((c) => c.setCellAttribute('textAlign', 'left'))"
        >
          <template #icon>
            <AlignLeftOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="水平居中">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-table-toolbar__btn--active': cellTextAlign === 'center' }"
          aria-label="单元格水平居中"
          @click="run((c) => c.setCellAttribute('textAlign', 'center'))"
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
          :class="{ 'word-table-toolbar__btn--active': cellTextAlign === 'right' }"
          aria-label="单元格右对齐"
          @click="run((c) => c.setCellAttribute('textAlign', 'right'))"
        >
          <template #icon>
            <AlignRightOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 垂直对齐 -->
      <a-tooltip title="顶端对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-table-toolbar__btn--active': cellVerticalAlign === 'top' }"
          aria-label="单元格顶端对齐"
          @click="run((c) => c.setCellAttribute('verticalAlign', 'top'))"
        >
          <template #icon>
            <VerticalAlignTopOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="垂直居中">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-table-toolbar__btn--active': cellVerticalAlign === 'middle' }"
          aria-label="单元格垂直居中"
          @click="run((c) => c.setCellAttribute('verticalAlign', 'middle'))"
        >
          <template #icon>
            <VerticalAlignMiddleOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="底端对齐">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-table-toolbar__btn--active': cellVerticalAlign === 'bottom' }"
          aria-label="单元格底端对齐"
          @click="run((c) => c.setCellAttribute('verticalAlign', 'bottom'))"
        >
          <template #icon>
            <VerticalAlignBottomOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 表格/单元格属性：边框 + 底纹 -->
      <a-popover
        trigger="click"
        placement="bottom"
        overlay-class-name="word-table-toolbar-popover"
      >
        <template #content>
          <div class="word-table-toolbar__props">
            <div class="word-table-toolbar__prop-row">
              <span class="word-table-toolbar__prop-label">边框样式</span>
              <a-select
                size="small"
                style="width: 110px"
                :value="cellBorderStyle || undefined"
                placeholder="默认"
                :options="borderStyleOptions"
                allow-clear
                @change="(v: string | undefined) => setCellAttr('borderStyle', v)"
              />
            </div>
            <div class="word-table-toolbar__prop-row">
              <span class="word-table-toolbar__prop-label">边框颜色</span>
              <input
                type="color"
                class="word-table-toolbar__color-input"
                :value="cellBorderColor || '#dee0e3'"
                aria-label="边框颜色"
                @input="setCellAttr('borderColor', ($event.target as HTMLInputElement).value)"
              >
              <a-button
                size="small"
                type="link"
                @click="setCellAttr('borderColor', undefined)"
              >
                清除
              </a-button>
            </div>
            <div class="word-table-toolbar__prop-row">
              <span class="word-table-toolbar__prop-label">边框宽度</span>
              <a-input-number
                size="small"
                style="width: 90px"
                :min="0"
                :max="20"
                :value="borderWidthPx"
                addon-after="px"
                placeholder="默认"
                @change="(v: number | string | null | undefined) => setCellAttr('borderWidth', typeof v === 'number' ? `${v}px` : undefined)"
              />
            </div>
            <div class="word-table-toolbar__prop-row">
              <span class="word-table-toolbar__prop-label">底纹颜色</span>
              <input
                type="color"
                class="word-table-toolbar__color-input"
                :value="cellBackgroundColor || '#ffffff'"
                aria-label="底纹颜色"
                @input="setCellAttr('backgroundColor', ($event.target as HTMLInputElement).value)"
              >
              <a-button
                size="small"
                type="link"
                @click="setCellAttr('backgroundColor', undefined)"
              >
                清除
              </a-button>
            </div>
          </div>
        </template>
        <a-tooltip title="表格属性">
          <a-button
            size="small"
            type="text"
            aria-label="表格属性"
          >
            <template #icon>
              <BgColorsOutlined />
            </template>
          </a-button>
        </a-tooltip>
      </a-popover>
    </a-space>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorTableToolbar：表格操作浮动工具栏。
 * - 仅在光标位于表格内（isActive('table')）时渲染。
 * - 行/列增删、合并/拆分、表头切换、单元格对齐（水平+垂直）、边框与底纹属性。
 * - 按钮状态随 editor transaction 版本号刷新；属性弹层内联设置单元格内联样式。
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import type { Editor, ChainedCommands } from '@tiptap/core'
import {
  BorderTopOutlined,
  BorderBottomOutlined,
  BorderLeftOutlined,
  BorderRightOutlined,
  BorderOuterOutlined,
  MinusOutlined,
  DeleteOutlined,
  ColumnHeightOutlined,
  ColumnWidthOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
  VerticalAlignTopOutlined,
  VerticalAlignMiddleOutlined,
  VerticalAlignBottomOutlined,
  BgColorsOutlined,
} from '@ant-design/icons-vue'

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
}>()

/* 事务版本号：editor 状态变化时递增，驱动 computed/按钮状态刷新 */
const version = ref(0)
const bump = () => {
  version.value++
}

watch(
  () => props.editor,
  (editor, _old, onCleanup) => {
    if (!editor) return
    editor.on('transaction', bump)
    onCleanup(() => editor.off('transaction', bump))
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  props.editor?.off('transaction', bump)
})

/** 执行一条链式命令（统一 focus） */
const run = (apply: (chain: ChainedCommands) => ChainedCommands) => {
  const editor = props.editor
  if (!editor) return
  apply(editor.chain().focus()).run()
}

/** 是否处于表格内 */
const inTable = computed(() => {
  void version.value
  return props.editor?.isActive('table') ?? false
})

/** 是否可合并单元格 */
const canMerge = computed(() => {
  void version.value
  return props.editor?.can().mergeCells() ?? false
})

/** 是否可拆分单元格 */
const canSplit = computed(() => {
  void version.value
  return props.editor?.can().splitCell() ?? false
})

/** 当前单元格属性（对齐/边框/底纹） */
const cellAttrs = computed<Record<string, unknown>>(() => {
  void version.value
  return props.editor?.getAttributes('tableCell') ?? {}
})

const cellTextAlign = computed(() => (cellAttrs.value.textAlign as string | undefined) ?? undefined)
const cellVerticalAlign = computed(() => (cellAttrs.value.verticalAlign as string | undefined) ?? undefined)
const cellBorderStyle = computed(() => (cellAttrs.value.borderStyle as string | undefined) ?? undefined)
const cellBorderColor = computed(() => (cellAttrs.value.borderColor as string | undefined) ?? undefined)
const cellBackgroundColor = computed(
  () => (cellAttrs.value.backgroundColor as string | undefined) ?? undefined,
)

/** 边框宽度（px 数值，用于 InputNumber） */
const borderWidthPx = computed(() => {
  const raw = cellAttrs.value.borderWidth as string | undefined
  if (!raw) return undefined
  const num = parseFloat(raw)
  return Number.isFinite(num) ? num : undefined
})

/** 边框样式选项 */
const borderStyleOptions = [
  { label: '实线', value: 'solid' },
  { label: '虚线', value: 'dashed' },
  { label: '点线', value: 'dotted' },
  { label: '无', value: 'none' },
]

/** 设置/清除单元格属性（undefined 表示清除） */
const setCellAttr = (name: string, value: string | undefined) => {
  run((c) => c.setCellAttribute(name, value ?? null))
}
</script>

<style scoped>
.word-table-toolbar {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
  padding: var(--space-1) var(--space-2);
}

/* 激活态按钮：主色 + 主色浅底 */
.word-table-toolbar__btn--active {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

/* 属性弹层内部布局 */
.word-table-toolbar__props {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 220px;
}
.word-table-toolbar__prop-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.word-table-toolbar__prop-label {
  flex: 0 0 64px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}
.word-table-toolbar__color-input {
  width: 32px;
  height: 24px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-surface);
  cursor: pointer;
}
</style>

<!-- 属性弹层 teleport 到 body，需非 scoped 样式适配深色 -->
<style>
.word-table-toolbar-popover .ant-popover-inner {
  background: var(--bg-elevated);
}
</style>
