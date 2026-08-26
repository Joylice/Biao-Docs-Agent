<template>
  <div
    v-if="visible && position"
    class="word-image-toolbar"
    role="toolbar"
    aria-label="图片工具栏"
    :style="{ top: `${position.top}px`, left: `${position.left}px` }"
  >
    <a-space :size="2">
      <!-- 更换图片 -->
      <a-tooltip title="更换图片">
        <a-button
          size="small"
          type="text"
          :disabled="!uploadImage"
          aria-label="更换图片"
          @click="triggerReplace"
        >
          <template #icon>
            <PictureOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 宽度 -->
      <span class="word-image-toolbar__label">宽</span>
      <a-input-number
        size="small"
        style="width: 72px"
        :min="20"
        :max="2000"
        :value="widthPx"
        placeholder="自动"
        addon-after="px"
        @change="onWidthChange"
      />
      <!-- 高度 -->
      <span class="word-image-toolbar__label">高</span>
      <a-input-number
        size="small"
        style="width: 72px"
        :min="20"
        :max="2000"
        :value="heightPx"
        placeholder="自动"
        addon-after="px"
        @change="onHeightChange"
      />

      <a-divider type="vertical" />

      <!-- 对齐（浮动）：左 / 中 / 右 -->
      <a-tooltip title="左浮动">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-image-toolbar__btn--active': floatVal === 'left' }"
          aria-label="图片左浮动"
          @click="run((c) => c.updateAttributes('image', { float: 'left' }))"
        >
          <template #icon>
            <AlignLeftOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="居中（取消浮动）">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-image-toolbar__btn--active': !floatVal }"
          aria-label="图片居中"
          @click="run((c) => c.updateAttributes('image', { float: null }))"
        >
          <template #icon>
            <AlignCenterOutlined />
          </template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="右浮动">
        <a-button
          size="small"
          type="text"
          :class="{ 'word-image-toolbar__btn--active': floatVal === 'right' }"
          aria-label="图片右浮动"
          @click="run((c) => c.updateAttributes('image', { float: 'right' }))"
        >
          <template #icon>
            <AlignRightOutlined />
          </template>
        </a-button>
      </a-tooltip>

      <a-divider type="vertical" />

      <!-- 边框样式 -->
      <a-select
        size="small"
        style="width: 88px"
        :value="imageBorderStyle || undefined"
        placeholder="边框"
        :options="borderStyleOptions"
        allow-clear
        @change="(v: any) => setImgAttr('borderStyle', v)"
      />
      <input
        type="color"
        class="word-image-toolbar__color-input"
        :value="imageBorderColor || '#dee0e3'"
        aria-label="图片边框颜色"
        @input="setImgAttr('borderColor', ($event.target as HTMLInputElement).value)"
      >
    </a-space>

    <!-- 隐藏文件选择器（更换图片） -->
    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      class="word-image-toolbar__file-input"
      @change="handleFileChange"
    >
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorImageToolbar：选中图片时浮现的浮动工具栏。
 * - 仅 editor.isActive('image') 时显示，定位在图片上方（coordsAtPos 视口坐标）。
 * - 更换图片 / 宽高 / 浮动对齐 / 边框样式与颜色。
 * - 更换图片需父组件注入 uploadImage（ (file) => Promise<url> ），未注入时禁用。
 * - 位置随事务版本号与滚动事件刷新（滚动监听挂到编辑区最近的可滚动父级）。
 */
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { Editor, ChainedCommands } from '@tiptap/core'
import {
  PictureOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
} from '@ant-design/icons-vue'

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 图片上传函数（注入后启用「更换图片」） */
  uploadImage?: (file: File) => Promise<string>
}>()

/* 事务版本号 */
const version = ref(0)
const bump = () => {
  version.value++
}

/* 滚动监听：刷新位置（挂到编辑区可滚动父级 + window 兜底） */
let scrollParent: HTMLElement | null = null
const onScroll = () => bump()
const findScrollParent = (el: HTMLElement | null): HTMLElement | null => {
  let node = el?.parentElement ?? null
  while (node) {
    if (/auto|scroll|overlay/.test(getComputedStyle(node).overflowY)) return node
    node = node.parentElement
  }
  return null
}

watch(
  () => props.editor,
  (editor, _old, onCleanup) => {
    if (!editor) return
    editor.on('transaction', bump)
    scrollParent = findScrollParent(editor.view.dom)
    scrollParent?.addEventListener('scroll', onScroll, { passive: true })
    onCleanup(() => {
      editor.off('transaction', bump)
      scrollParent?.removeEventListener('scroll', onScroll)
    })
  },
  { immediate: true },
)

onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onBeforeUnmount(() => {
  props.editor?.off('transaction', bump)
  scrollParent?.removeEventListener('scroll', onScroll)
  window.removeEventListener('scroll', onScroll)
})

/** 执行链式命令 */
const run = (apply: (chain: ChainedCommands) => ChainedCommands) => {
  const editor = props.editor
  if (!editor) return
  apply(editor.chain().focus()).run()
}

/** 选中图片时显示 */
const visible = computed(() => {
  void version.value
  return props.editor?.isActive('image') ?? false
})

/** 选中图片节点的屏幕坐标（上方居中） */
const position = computed<{ top: number; left: number } | null>(() => {
  void version.value
  const editor = props.editor
  if (!editor || !editor.isActive('image')) return null
  try {
    const { from } = editor.state.selection
    const coords = editor.view.coordsAtPos(from)
    return {
      top: Math.max(coords.top - 44, 4),
      left: coords.left + (coords.right - coords.left) / 2,
    }
  } catch {
    return null
  }
})

/** 当前图片属性 */
const imageAttrs = computed<Record<string, unknown>>(() => {
  void version.value
  return props.editor?.getAttributes('image') ?? {}
})

const widthPx = computed(() => parsePx(imageAttrs.value.width as string | undefined))
const heightPx = computed(() => parsePx(imageAttrs.value.height as string | undefined))
const floatVal = computed(() => (imageAttrs.value.float as string | undefined) ?? undefined)
const imageBorderStyle = computed(
  () => (imageAttrs.value.borderStyle as string | undefined) ?? undefined,
)
const imageBorderColor = computed(
  () => (imageAttrs.value.borderColor as string | undefined) ?? undefined,
)

/** 解析 "Npx" 为数值 */
const parsePx = (value: string | undefined): number | undefined => {
  if (!value) return undefined
  const num = parseFloat(value)
  return Number.isFinite(num) ? num : undefined
}

/** 边框样式选项 */
const borderStyleOptions = [
  { label: '实线', value: 'solid' },
  { label: '虚线', value: 'dashed' },
  { label: '点线', value: 'dotted' },
  { label: '无', value: 'none' },
]

/** 设置/清除图片属性 */
const setImgAttr = (name: string, value: string | undefined) => {
  run((c) => c.updateAttributes('image', { [name]: value ?? null }))
}

const onWidthChange = (v: number | string | null | undefined) => {
  setImgAttr('width', typeof v === 'number' && v > 0 ? `${v}px` : undefined)
}
const onHeightChange = (v: number | string | null | undefined) => {
  setImgAttr('height', typeof v === 'number' && v > 0 ? `${v}px` : undefined)
}

/* ---------- 更换图片 ---------- */
const fileInputRef = ref<HTMLInputElement | null>(null)

const triggerReplace = () => {
  fileInputRef.value?.click()
}

const handleFileChange = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选择同一文件
  if (!file) return
  const upload = props.uploadImage
  if (!upload) return
  try {
    const url = await upload(file)
    run((c) => c.updateAttributes('image', { src: url }))
  } catch {
    // 上传错误由调用方（useImageUpload）处理
  }
}
</script>

<style scoped>
.word-image-toolbar {
  position: fixed;
  z-index: 1000;
  transform: translateX(-50%);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-md);
  padding: var(--space-1) var(--space-2);
  display: flex;
  align-items: center;
}

.word-image-toolbar__label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  margin-left: var(--space-1);
}

.word-image-toolbar__btn--active {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.word-image-toolbar__color-input {
  width: 28px;
  height: 22px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-surface);
  cursor: pointer;
}

.word-image-toolbar__file-input {
  display: none;
}
</style>
