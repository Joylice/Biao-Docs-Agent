<template>
  <div
    class="word-properties"
    :class="{ 'word-properties--dark': isDark }"
    role="complementary"
    aria-label="属性面板"
  >
    <div class="word-properties__header">
      <span class="word-properties__title">属性</span>
      <a-button
        size="small"
        type="text"
        @click="$emit('close')"
        aria-label="关闭属性面板"
      >
        <template #icon>
          <CloseOutlined />
        </template>
      </a-button>
    </div>

    <div class="word-properties__body">
      <!-- 无选中内容时显示提示 -->
      <div v-if="!hasSelection && !isInTable && !isInImage" class="word-properties__empty">
        <InfoCircleOutlined class="word-properties__empty-icon" />
        <p>将光标放在段落中或选中内容</p>
        <p class="word-properties__empty-hint">即可查看和编辑属性</p>
      </div>

      <!-- 段落属性 -->
      <div v-if="hasSelection || isInParagraph" class="word-properties__section">
        <div class="word-properties__section-title">段落</div>

        <!-- 对齐方式 -->
        <div class="word-properties__row">
          <span class="word-properties__label">对齐</span>
          <a-button-group size="small">
            <a-button
              :type="textAlign === 'left' ? 'primary' : 'default'"
              @click="setTextAlign('left')"
              title="左对齐"
            >
              <template #icon><AlignLeftOutlined /></template>
            </a-button>
            <a-button
              :type="textAlign === 'center' ? 'primary' : 'default'"
              @click="setTextAlign('center')"
              title="居中"
            >
              <template #icon><AlignCenterOutlined /></template>
            </a-button>
            <a-button
              :type="textAlign === 'right' ? 'primary' : 'default'"
              @click="setTextAlign('right')"
              title="右对齐"
            >
              <template #icon><AlignRightOutlined /></template>
            </a-button>
            <a-button
              :type="textAlign === 'justify' ? 'primary' : 'default'"
              @click="setTextAlign('justify')"
              title="两端对齐"
            >
              <template #icon><MenuOutlined /></template>
            </a-button>
          </a-button-group>
        </div>

        <!-- 行距 -->
        <div class="word-properties__row">
          <span class="word-properties__label">行距</span>
          <a-select
            :value="lineHeight"
            size="small"
            class="word-properties__select"
            :options="lineHeightOptions"
            @change="setLineHeight"
          />
        </div>

        <!-- 首行缩进 -->
        <div class="word-properties__row">
          <span class="word-properties__label">首行缩进</span>
          <a-select
            :value="String(firstLineIndent)"
            size="small"
            class="word-properties__select"
            :options="indentOptions"
            @change="setFirstLineIndent"
          />
        </div>

        <!-- 段前段后 -->
        <div class="word-properties__row">
          <span class="word-properties__label">段前</span>
          <a-input-number
            :value="paragraphSpacing.before"
            :min="0"
            :max="100"
            size="small"
            style="width: 70px"
            @change="setParagraphSpacing('before', $event)"
          />
          <span class="word-properties__unit">pt</span>
        </div>
        <div class="word-properties__row">
          <span class="word-properties__label">段后</span>
          <a-input-number
            :value="paragraphSpacing.after"
            :min="0"
            :max="100"
            size="small"
            style="width: 70px"
            @change="setParagraphSpacing('after', $event)"
          />
          <span class="word-properties__unit">pt</span>
        </div>
      </div>

      <!-- 字体属性 -->
      <div v-if="hasSelection" class="word-properties__section">
        <div class="word-properties__section-title">字体</div>

        <!-- 字体 -->
        <div class="word-properties__row">
          <span class="word-properties__label">字体</span>
          <a-select
            :value="fontFamily"
            size="small"
            class="word-properties__select"
            :options="fontFamilyOptions"
            @change="setFontFamily"
          />
        </div>

        <!-- 字号 -->
        <div class="word-properties__row">
          <span class="word-properties__label">字号</span>
          <a-select
            :value="fontSize"
            size="small"
            class="word-properties__select"
            :options="fontSizeOptions"
            @change="setFontSize"
          />
        </div>

        <!-- 文字颜色 -->
        <div class="word-properties__row">
          <span class="word-properties__label">文字颜色</span>
          <div class="word-properties__color-row">
            <div
              class="word-properties__color-preview"
              :style="{ background: textColor || '#000000' }"
            />
            <a-popover trigger="click" placement="bottom">
              <template #content>
                <div class="word-properties__palette">
                  <button
                    v-for="color in TEXT_COLOR_PRESETS"
                    :key="color"
                    type="button"
                    class="word-properties__swatch"
                    :style="{ background: color }"
                    @click="setTextColor(color)"
                  />
                </div>
              </template>
              <a-button size="small">选择</a-button>
            </a-popover>
          </div>
        </div>

        <!-- 字重样式 -->
        <div class="word-properties__row">
          <span class="word-properties__label">样式</span>
          <a-button-group size="small">
            <a-button
              :type="isBold ? 'primary' : 'default'"
              @click="toggleBold"
              title="加粗"
            >
              <strong>B</strong>
            </a-button>
            <a-button
              :type="isItalic ? 'primary' : 'default'"
              @click="toggleItalic"
              title="斜体"
            >
              <em>I</em>
            </a-button>
            <a-button
              :type="isUnderline ? 'primary' : 'default'"
              @click="toggleUnderline"
              title="下划线"
            >
              <u>U</u>
            </a-button>
            <a-button
              :type="isStrike ? 'primary' : 'default'"
              @click="toggleStrike"
              title="删除线"
            >
              <s>S</s>
            </a-button>
          </a-button-group>
        </div>
      </div>

      <!-- 表格属性 -->
      <div v-if="isInTable" class="word-properties__section">
        <div class="word-properties__section-title">表格</div>
        <div class="word-properties__row">
          <span class="word-properties__label">单元格对齐</span>
          <a-button-group size="small">
            <a-button
              v-for="align in tableCellAligns"
              :key="align.value"
              :type="tableCellAlign === align.value ? 'primary' : 'default'"
              @click="setTableCellAlign(align.value)"
              :title="align.label"
            >
              {{ align.icon }}
            </a-button>
          </a-button-group>
        </div>
        <div class="word-properties__row">
          <span class="word-properties__label">边框颜色</span>
          <a-popover trigger="click" placement="bottom">
            <template #content>
              <div class="word-properties__palette">
                <button
                  v-for="color in BORDER_COLOR_PRESETS"
                  :key="color"
                  type="button"
                  class="word-properties__swatch"
                  :style="{ background: color }"
                  @click="setTableBorderColor(color)"
                />
              </div>
            </template>
            <a-button size="small">选择</a-button>
          </a-popover>
        </div>
        <div class="word-properties__row">
          <span class="word-properties__label">底纹颜色</span>
          <a-popover trigger="click" placement="bottom">
            <template #content>
              <div class="word-properties__palette">
                <button
                  v-for="color in BG_COLOR_PRESETS"
                  :key="color"
                  type="button"
                  class="word-properties__swatch"
                  :style="{ background: color }"
                  @click="setTableBgColor(color)"
                />
                <button
                  type="button"
                  class="word-properties__swatch-reset"
                  @click="setTableBgColor('')"
                >无</button>
              </div>
            </template>
            <a-button size="small">选择</a-button>
          </a-popover>
        </div>
      </div>

      <!-- 图片属性 -->
      <div v-if="isInImage" class="word-properties__section">
        <div class="word-properties__section-title">图片</div>
        <div class="word-properties__row">
          <span class="word-properties__label">宽度</span>
          <a-input-number
            :value="imageWidth"
            :min="20"
            :max="2000"
            size="small"
            style="width: 90px"
            @change="setImageWidth"
          />
          <span class="word-properties__unit">px</span>
        </div>
        <div class="word-properties__row">
          <span class="word-properties__label">高度</span>
          <a-input-number
            :value="imageHeight"
            :min="20"
            :max="2000"
            size="small"
            style="width: 90px"
            @change="setImageHeight"
          />
          <span class="word-properties__unit">px</span>
        </div>
        <div class="word-properties__row">
          <span class="word-properties__label">对齐</span>
          <a-button-group size="small">
            <a-button
              :type="imageAlign === 'left' ? 'primary' : 'default'"
              @click="setImageAlign('left')"
              title="左对齐"
            >
              <template #icon><AlignLeftOutlined /></template>
            </a-button>
            <a-button
              :type="imageAlign === 'center' ? 'primary' : 'default'"
              @click="setImageAlign('center')"
              title="居中"
            >
              <template #icon><AlignCenterOutlined /></template>
            </a-button>
            <a-button
              :type="imageAlign === 'right' ? 'primary' : 'default'"
              @click="setImageAlign('right')"
              title="右对齐"
            >
              <template #icon><AlignRightOutlined /></template>
            </a-button>
          </a-button-group>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorProperties：右侧属性面板
 * - 实时响应编辑器选中内容变化
 * - 段落属性：对齐/行距/首行缩进/段前段后
 * - 字体属性：字体/字号/颜色/加粗/斜体/下划线/删除线
 * - 表格属性：单元格对齐/边框颜色/底纹颜色
 * - 图片属性：宽度/高度/对齐
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  CloseOutlined,
  InfoCircleOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
  MenuOutlined,
} from '@ant-design/icons-vue'
import { FONT_FAMILY_OPTIONS } from './extensions/font-family'
import { FONT_SIZE_OPTIONS } from './extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from './extensions/line-height'
import { TEXT_COLOR_PRESETS } from './extensions/text-color'

const props = defineProps<{
  editor?: Editor
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

/* 事务版本号：强制 computed 重新求值 */
const version = ref(0)
const bump = () => { version.value++ }

/* 编辑器状态 */
const hasSelection = computed(() => {
  void version.value
  const ed = props.editor
  if (!ed) return false
  return !ed.state.selection.empty
})

const isInParagraph = computed(() => {
  void version.value
  return props.editor?.isActive('paragraph') ?? false
})

const isInTable = computed(() => {
  void version.value
  return props.editor?.isActive('table') ?? false
})

const isInImage = computed(() => {
  void version.value
  return props.editor?.isActive('image') ?? false
})

/* 段落属性 */
const textAlign = computed(() => {
  void version.value
  const attrs = props.editor?.getAttributes('paragraph')
  return (attrs?.textAlign as string) || 'left'
})

const lineHeight = computed(() => {
  void version.value
  const attrs = props.editor?.isActive('heading')
    ? props.editor?.getAttributes('heading')
    : props.editor?.getAttributes('paragraph')
  return (attrs?.lineHeight as string) || '1.5'
})

const firstLineIndent = computed(() => {
  void version.value
  const attrs = props.editor?.isActive('heading')
    ? props.editor?.getAttributes('heading')
    : props.editor?.getAttributes('paragraph')
  const indent = attrs?.textIndent as string | undefined
  if (indent && indent.endsWith('em')) {
    return parseFloat(indent)
  }
  return 0
})

const paragraphSpacing = ref({ before: 0, after: 0 })

/* 字体属性 */
const textStyleAttrs = computed(() => {
  void version.value
  return props.editor?.getAttributes('textStyle') ?? {}
})

const fontFamily = computed(() => (textStyleAttrs.value.fontFamily as string) || undefined)
const fontSize = computed(() => (textStyleAttrs.value.fontSize as string) || undefined)
const textColor = computed(() => (textStyleAttrs.value.color as string) || undefined)

const isBold = computed(() => { void version.value; return props.editor?.isActive('bold') ?? false })
const isItalic = computed(() => { void version.value; return props.editor?.isActive('italic') ?? false })
const isUnderline = computed(() => { void version.value; return props.editor?.isActive('underline') ?? false })
const isStrike = computed(() => { void version.value; return props.editor?.isActive('strike') ?? false })

/* 表格属性 */
const tableCellAlign = computed(() => {
  void version.value
  const attrs = props.editor?.getAttributes('tableCell')
  return (attrs?.textAlign as string) || 'left'
})

/* 图片属性 */
const imageAttrs = computed(() => {
  void version.value
  return props.editor?.getAttributes('image') ?? {}
})

const imageWidth = computed(() => Number(imageAttrs.value.width) || 300)
const imageHeight = computed(() => Number(imageAttrs.value.height) || 200)
const imageAlign = computed(() => (imageAttrs.value.align as string) || 'left')

/* 选项 */
const fontFamilyOptions = FONT_FAMILY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
const fontSizeOptions = FONT_SIZE_OPTIONS.map((o) => ({ label: `${o.label} · ${o.value}`, value: o.value }))
const lineHeightOptions = LINE_HEIGHT_OPTIONS.map((v) => ({ label: `行高 ${v}`, value: String(v) }))
const indentOptions = [
  { label: '无', value: '0' },
  { label: '2字符', value: '2' },
  { label: '4字符', value: '4' },
  { label: '6字符', value: '6' },
]

const tableCellAligns = [
  { value: 'left', label: '左上', icon: '↖' },
  { value: 'center', label: '中上', icon: '↑' },
  { value: 'right', label: '右上', icon: '↗' },
]

const BORDER_COLOR_PRESETS = ['#000000', '#333333', '#666666', '#999999', '#cccccc', '#1890ff', '#52c41a', '#faad14', '#f5222d']
const BG_COLOR_PRESETS = ['#ffffff', '#f5f5f5', '#e6f7ff', '#f6ffed', '#fff7e6', '#fff1f0', '#f9f0ff', '#e6fffb']

/* 操作方法 */
const run = (fn: (chain: any) => any) => {
  const ed = props.editor
  if (!ed) return
  fn(ed.chain().focus()).run()
}

const setTextAlign = (align: string) => run((c: any) => c.setTextAlign(align))
const setLineHeight = (val: any) => run((c: any) => c.setLineHeight(val))
const setFirstLineIndent = (val: any) => run((c: any) => c.setIndent(Number(val)))
const setParagraphSpacing = (_type: string, _val: any) => {
  // Tiptap 默认不支持段前段后，需自定义扩展；此处预留
}

const setFontFamily = (val: any) => run((c: any) => c.setFontFamily(val))
const setFontSize = (val: any) => run((c: any) => c.setFontSize(val))
const setTextColor = (color: string) => run((c: any) => c.setColor(color))
const toggleBold = () => run((c: any) => c.toggleBold())
const toggleItalic = () => run((c: any) => c.toggleItalic())
const toggleUnderline = () => run((c: any) => c.toggleUnderline())
const toggleStrike = () => run((c: any) => c.toggleStrike())

const setTableCellAlign = (align: string) => {
  const ed = props.editor
  if (!ed) return
  ed.chain().focus().updateAttributes('tableCell', { textAlign: align }).run()
}

const setTableBorderColor = (_color: string) => {
  // 需自定义表格扩展支持边框颜色；预留
}

const setTableBgColor = (color: string) => {
  const ed = props.editor
  if (!ed) return
  ed.chain().focus().updateAttributes('tableCell', { backgroundColor: color || null }).run()
}

const setImageWidth = (val: any) => {
  if (val == null) return
  const ed = props.editor
  if (!ed) return
  ed.chain().focus().updateAttributes('image', { width: Number(val) }).run()
}

const setImageHeight = (val: any) => {
  if (val == null) return
  const ed = props.editor
  if (!ed) return
  ed.chain().focus().updateAttributes('image', { height: Number(val) }).run()
}

const setImageAlign = (align: string) => {
  const ed = props.editor
  if (!ed) return
  ed.chain().focus().updateAttributes('image', { align }).run()
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
})

watch(() => props.editor, (ed, oldEd) => {
  if (oldEd && transactionHandler) oldEd.off('transaction', transactionHandler)
  if (ed) {
    transactionHandler = bump
    ed.on('transaction', transactionHandler)
  }
})

onBeforeUnmount(() => {
  darkObserver?.disconnect()
  if (props.editor && transactionHandler) {
    props.editor.off('transaction', transactionHandler)
  }
})
</script>

<style scoped>
.word-properties {
  width: 260px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-color);
  font-size: var(--font-size-sm);
}

.word-properties__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-color);
}

.word-properties__title {
  font-weight: 600;
  color: var(--text-primary);
}

.word-properties__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
}

.word-properties__empty {
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--text-tertiary);
}
.word-properties__empty-icon {
  font-size: 32px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}
.word-properties__empty p {
  margin: var(--space-1) 0;
}
.word-properties__empty-hint {
  font-size: var(--font-size-xs);
  opacity: 0.7;
}

.word-properties__section {
  margin-bottom: var(--space-4);
}

.word-properties__section-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  margin-bottom: var(--space-2);
  padding-bottom: var(--space-1);
  border-bottom: 1px solid var(--border-color);
}

.word-properties__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.word-properties__label {
  width: 60px;
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.word-properties__select {
  flex: 1;
  min-width: 0;
}

.word-properties__unit {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.word-properties__color-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
}

.word-properties__color-preview {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}

.word-properties__palette {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-2);
}

.word-properties__swatch {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-color);
  cursor: pointer;
  padding: 0;
}
.word-properties__swatch:hover {
  transform: scale(1.1);
}

.word-properties__swatch-reset {
  grid-column: span 5;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  padding: 3px 0;
  cursor: pointer;
}
</style>
