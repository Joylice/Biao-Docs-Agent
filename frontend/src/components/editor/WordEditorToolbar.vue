<template>
  <a-tabs
    v-model:activeKey="activeTab"
    type="card"
    size="small"
    class="word-toolbar"
    role="toolbar"
    aria-label="编辑器格式工具栏"
  >
    <!-- ==================== 「开始」选项卡 ==================== -->
    <a-tab-pane
      key="home"
      tab="开始"
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
    </a-tab-pane>

    <!-- ==================== 「插入」选项卡 ==================== -->
    <a-tab-pane
      key="insert"
      tab="插入"
    >
      <a-space
        wrap
        :size="2"
        class="word-toolbar__group"
      >
        <!-- 表格 -->
        <a-popover
          trigger="click"
          placement="bottom"
          overlay-class-name="word-toolbar-popover"
        >
          <template #content>
            <div class="word-toolbar__table-picker">
              <span class="word-toolbar__picker-label">行</span>
              <a-input-number
                v-model:value="tableRows"
                :min="1"
                :max="20"
                size="small"
                style="width: 64px"
              />
              <span class="word-toolbar__picker-label">列</span>
              <a-input-number
                v-model:value="tableCols"
                :min="1"
                :max="20"
                size="small"
                style="width: 64px"
              />
              <a-button
                size="small"
                type="primary"
                @click="handleInsertTable"
              >
                插入
              </a-button>
            </div>
          </template>
          <a-tooltip title="插入表格">
            <a-button
              size="small"
              type="text"
              aria-label="插入表格"
            >
              <template #icon>
                <TableOutlined />
              </template>
              表格
            </a-button>
          </a-tooltip>
        </a-popover>

        <!-- 图片 -->
        <a-tooltip :title="props.uploadImage ? '插入图片' : '需要传入 uploadImage 属性'">
          <a-button
            size="small"
            type="text"
            :disabled="!props.uploadImage"
            aria-label="插入图片"
            @click="triggerImageUpload"
          >
            <template #icon>
              <PictureOutlined />
            </template>
            图片
          </a-button>
        </a-tooltip>
        <input
          ref="imageInputRef"
          type="file"
          accept="image/*"
          class="word-toolbar__file-input"
          @change="handleImageSelect"
        >

        <!-- 链接 -->
        <a-popover
          trigger="click"
          placement="bottom"
          overlay-class-name="word-toolbar-popover"
        >
          <template #content>
            <div class="word-toolbar__link-input">
              <a-input
                v-model:value="linkUrl"
                size="small"
                placeholder="https://"
                style="width: 200px"
                @keydown.enter.prevent="handleInsertLink"
              />
              <a-button
                size="small"
                type="primary"
                @click="handleInsertLink"
              >
                插入
              </a-button>
            </div>
          </template>
          <a-tooltip title="插入链接">
            <a-button
              size="small"
              type="text"
              aria-label="插入链接"
            >
              <template #icon>
                <LinkOutlined />
              </template>
              链接
            </a-button>
          </a-tooltip>
        </a-popover>

        <a-divider type="vertical" />

        <!-- 分页符 -->
        <a-tooltip title="插入分页符 (Ctrl+Enter)">
          <a-button
            size="small"
            type="text"
            aria-label="分页符"
            @click="run((chain) => chain.setPageBreak())"
          >
            <template #icon>
              <ColumnHeightOutlined />
            </template>
            分页符
          </a-button>
        </a-tooltip>

        <a-divider type="vertical" />

        <!-- 符号（P2） -->
        <a-tooltip title="P2 实现">
          <a-button
            size="small"
            type="text"
            disabled
            aria-label="符号"
          >
            <template #icon>
              <FontSizeOutlined />
            </template>
            符号
          </a-button>
        </a-tooltip>

        <!-- 页眉页脚（导出 Word/打印时自动生成，编辑态暂不开放） -->
        <a-tooltip title="导出 Word / 打印时自动生成页眉页脚">
          <a-button
            size="small"
            type="text"
            disabled
            aria-label="页眉页脚"
          >
            <template #icon>
              <LayoutOutlined />
            </template>
            页眉页脚
          </a-button>
        </a-tooltip>

        <!-- 批注（P3 已集成：打开右侧批注面板） -->
        <a-tooltip title="批注">
          <a-button
            size="small"
            type="text"
            aria-label="批注"
            @click="emit('openComments')"
          >
            <template #icon>
              <CommentOutlined />
            </template>
            批注
          </a-button>
        </a-tooltip>
      </a-space>
    </a-tab-pane>

    <!-- ==================== 「布局」选项卡 ==================== -->
    <a-tab-pane
      key="layout"
      tab="布局"
    >
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

        <!-- 缩进（复用 P0） -->
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

        <!-- 行距（复用 P0） -->
        <span class="word-toolbar__label">行距</span>
        <a-select
          :value="currentLineHeight"
          size="small"
          class="word-toolbar__select word-toolbar__select--line-height"
          :options="lineHeightOptions"
          @change="handleLineHeightChange"
        />
      </a-space>
    </a-tab-pane>

    <!-- ==================== 「视图」选项卡 ==================== -->
    <a-tab-pane
      key="view"
      tab="视图"
    >
      <a-space
        wrap
        :size="2"
        class="word-toolbar__group"
      >
        <!-- 标尺（P2） -->
        <a-tooltip title="P2 实现">
          <span class="word-toolbar__switch-wrap">
            <a-switch
              v-model:checked="rulerVisible"
              size="small"
              disabled
            />
            <span class="word-toolbar__label">标尺</span>
          </span>
        </a-tooltip>

        <!-- 网格线（P2） -->
        <a-tooltip title="P2 实现">
          <span class="word-toolbar__switch-wrap">
            <a-switch
              v-model:checked="gridVisible"
              size="small"
              disabled
            />
            <span class="word-toolbar__label">网格</span>
          </span>
        </a-tooltip>

        <a-divider type="vertical" />

        <!-- 导航窗格 -->
        <span class="word-toolbar__switch-wrap">
          <a-switch
            v-model:checked="outlineVisible"
            size="small"
          />
          <span class="word-toolbar__label">导航窗格</span>
        </span>

        <a-divider type="vertical" />

        <!-- 缩放 -->
        <span class="word-toolbar__label">缩放</span>
        <a-slider
          v-model:value="zoomValue"
          :min="10"
          :max="500"
          :step="10"
          style="width: 120px"
        />
        <span class="word-toolbar__zoom-value">{{ zoomValue }}%</span>

        <a-divider type="vertical" />

        <!-- 视图模式 -->
        <a-button-group>
          <a-button
            size="small"
            type="primary"
          >
            <template #icon>
              <FileTextOutlined />
            </template>
            页面
          </a-button>
          <a-tooltip title="P2 实现">
            <a-button
              size="small"
              disabled
            >
              <template #icon>
                <ReadOutlined />
              </template>
              大纲
            </a-button>
          </a-tooltip>
        </a-button-group>
      </a-space>
    </a-tab-pane>
  </a-tabs>
</template>

<script setup lang="ts">
/**
 * WordEditorToolbar：Ribbon 多选项卡工具栏
 * - 「开始」：P0 全部控件 + 格式刷（useFormatBrush）
 * - 「插入」：表格/图片/链接/分页符 + P2/P3 占位
 * - 「布局」：页边距/方向/纸张/缩进/行距
 * - 「视图」：标尺/网格/导航窗格/缩放/视图模式
 *
 * 通过 editor 实例驱动命令，借助 transaction 版本号强制同步按钮 active 状态。
 */
import { computed, ref, watch, onBeforeUnmount, inject } from 'vue'
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
  FormatPainterOutlined,
  TableOutlined,
  PictureOutlined,
  LinkOutlined,
  ColumnHeightOutlined,
  FontSizeOutlined,
  LayoutOutlined,
  CommentOutlined,
  FileTextOutlined,
  ReadOutlined,
} from '@ant-design/icons-vue'
import { FONT_FAMILY_OPTIONS } from './extensions/font-family'
import { FONT_SIZE_OPTIONS } from './extensions/font-size'
import { LINE_HEIGHT_OPTIONS } from './extensions/line-height'
import { TEXT_COLOR_PRESETS } from './extensions/text-color'
import { HIGHLIGHT_COLOR_PRESETS } from './extensions/highlight'
import type { UseFormatBrushReturn } from '@/composables/useFormatBrush'

const props = defineProps<{
  /** 编辑器实例（由父组件传入；未就绪时为 undefined） */
  editor: Editor | undefined
  /** 项目 ID（图片上传需要） */
  projectId?: string
  /** 图片上传函数（从 WordEditorPage 注入） */
  uploadImage?: (file: File) => Promise<string>
}>()

const emit = defineEmits<{
  (e: 'update:outlineVisible', value: boolean): void
  (e: 'update:zoom', value: number): void
  (e: 'openComments'): void
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

const handleParagraphChange = (value: any) => {
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

const handleFontFamilyChange = (value: any) => {
  run((chain) => chain.setFontFamily(value))
}

const handleFontSizeChange = (value: any) => {
  run((chain) => chain.setFontSize(value))
}

const handleLineHeightChange = (value: any) => {
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

/* ==================== Ribbon 选项卡 ==================== */
const activeTab = ref<string>('home')

/* ==================== 格式刷（单一实例，由 WordEditorPage provide） ==================== */
const formatBrush = inject<UseFormatBrushReturn | null>('formatBrush', null)
const brushActive = formatBrush?.brushActive ?? ref(false)
const copyFormat = formatBrush?.copyFormat ?? (() => {})

/** 单击/双击定时器：区分单击（单次格式刷）与双击（连续格式刷） */
let brushClickTimer: ReturnType<typeof setTimeout> | null = null

/** 单击：延迟 220ms 触发单次格式刷（等待 dblclick 可能取消） */
const handleBrushClick = () => {
  brushClickTimer = setTimeout(() => {
    copyFormat('single')
    brushClickTimer = null
  }, 220)
}

/** 双击：取消单击定时器，激活连续格式刷 */
const handleBrushDblClick = () => {
  if (brushClickTimer) {
    clearTimeout(brushClickTimer)
    brushClickTimer = null
  }
  copyFormat('continuous')
}

/* ==================== 插入选项卡 ==================== */
/** 表格行列选择器 */
const tableRows = ref(3)
const tableCols = ref(3)

const handleInsertTable = () => {
  run((chain) => chain.insertTable({ rows: tableRows.value, cols: tableCols.value, withHeaderRow: true }))
}

/** 图片上传隐藏 input */
const imageInputRef = ref<HTMLInputElement | null>(null)

const triggerImageUpload = () => {
  imageInputRef.value?.click()
}

const handleImageSelect = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !props.uploadImage) return
  try {
    const src = await props.uploadImage(file)
    run((chain) => chain.setImage({ src }))
  } catch {
    // 错误由 useImageUpload 处理
  }
  input.value = ''
}

/** 链接 URL 输入 */
const linkUrl = ref('')

const handleInsertLink = () => {
  if (linkUrl.value) {
    run((chain) => chain.setLink({ href: linkUrl.value }))
    linkUrl.value = ''
  }
}

/* ==================== 布局选项卡 ==================== */
/** 页边距：通过 CSS 变量 --paper-padding 控制纸面 padding（批 C 集成到 WordEditor） */
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

/** 纸张方向：通过 CSS 变量切换纸面宽高 */
const paperOrientation = ref<'portrait' | 'landscape'>('portrait')
const PAPER_DIMENSIONS: Record<string, [string, string]> = {
  A4: ['210mm', '297mm'],
  Letter: ['216mm', '279mm'],
  custom: ['210mm', '297mm'],
}
watch(paperOrientation, (val) => {
  const size = paperSize.value
  const [w, h] = PAPER_DIMENSIONS[size] ?? PAPER_DIMENSIONS.A4
  if (val === 'landscape') {
    document.documentElement.style.setProperty('--paper-width', h)
    document.documentElement.style.setProperty('--paper-height', w)
  } else {
    document.documentElement.style.setProperty('--paper-width', w)
    document.documentElement.style.setProperty('--paper-height', h)
  }
  document.documentElement.setAttribute('data-paper-orientation', val)
})

/** 纸张大小：通过 CSS 变量控制纸面尺寸 */
const paperSize = ref('A4')
const paperSizeOptions = [
  { label: 'A4', value: 'A4' },
  { label: 'Letter', value: 'Letter' },
  { label: '自定义', value: 'custom' },
]
watch(paperSize, (val) => {
  const [w, h] = PAPER_DIMENSIONS[val] ?? PAPER_DIMENSIONS.A4
  const orientation = paperOrientation.value
  if (orientation === 'landscape') {
    document.documentElement.style.setProperty('--paper-width', h)
    document.documentElement.style.setProperty('--paper-height', w)
  } else {
    document.documentElement.style.setProperty('--paper-width', w)
    document.documentElement.style.setProperty('--paper-height', h)
  }
  document.documentElement.setAttribute('data-paper-size', val)
})

/* ==================== 视图选项卡 ==================== */
/** 标尺/网格（P2 占位） */
const rulerVisible = ref(false)
const gridVisible = ref(false)

/** 导航窗格：emit 给 WordEditorPage 控制大纲面板显示 */
const outlineVisible = ref(false)
watch(outlineVisible, (val) => emit('update:outlineVisible', val))

/** 缩放：emit 给 WordEditorPage 控制纸面 transform: scale */
const zoomValue = ref(100)
watch(zoomValue, (val) => emit('update:zoom', val))

/* ==================== 生命周期 ==================== */
onBeforeUnmount(() => {
  props.editor?.off('transaction', bump)
  if (brushClickTimer) clearTimeout(brushClickTimer)
  /* W6: 清理全局 CSS 变量/data 属性，避免影响其他页面 */
  document.documentElement.style.removeProperty('--paper-padding')
  document.documentElement.style.removeProperty('--paper-width')
  document.documentElement.style.removeProperty('--paper-height')
  document.documentElement.removeAttribute('data-paper-orientation')
  document.documentElement.removeAttribute('data-paper-size')
})
</script>

<style scoped>
.word-toolbar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}

/* a-tabs card 样式：紧凑 tab 栏 + 无边框内容区 */
.word-toolbar :deep(.ant-tabs-small > .ant-tabs-nav) {
  margin: 0;
  padding: 0 var(--space-2);
}
.word-toolbar :deep(.ant-tabs-card > .ant-tabs-nav::before) {
  border-bottom: none;
}
.word-toolbar :deep(.ant-tabs-card .ant-tabs-tab) {
  background: var(--bg-surface-active);
  border-color: var(--border-color);
}
.word-toolbar :deep(.ant-tabs-card .ant-tabs-tab-active) {
  background: var(--bg-surface);
  border-bottom-color: var(--bg-surface);
}
.word-toolbar :deep(.ant-tabs-content-holder) {
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

/* 隐藏的图片上传 input */
.word-toolbar__file-input {
  display: none;
}

/* 表格行列选择器 */
.word-toolbar__table-picker {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.word-toolbar__picker-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

/* 链接输入 */
.word-toolbar__link-input {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 选项卡内文字标签 */
.word-toolbar__label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  white-space: nowrap;
}

/* 缩放百分比显示 */
.word-toolbar__zoom-value {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  min-width: 40px;
}

/* switch + 文字包裹（用于 tooltip 包裹 disabled switch） */
.word-toolbar__switch-wrap {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
</style>

<!-- 色板弹层渲染在 body 下（teleport），需非 scoped 样式覆盖深色适配 -->
<style>
.word-toolbar-popover .ant-popover-inner {
  background: var(--bg-elevated);
}
</style>
