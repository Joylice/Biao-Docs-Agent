<template>
  <div class="word-editor">
    <div
      ref="scrollRef"
      class="word-editor__scroll"
    >
      <!-- A4 纸面：宽 210mm、最小高 297mm、页边距 25.4mm -->
      <div
        ref="paperRef"
        class="word-editor__paper"
      >
        <EditorContent
          :editor="editor"
          class="word-editor__content"
        />
      </div>
    </div>

    <!-- 虚拟页码（滚动位置 → 当前页 / 总页数） -->
    <div
      v-if="totalPages > 1"
      class="word-editor__page-number"
    >
      第 {{ currentPage }} 页 / 共 {{ totalPages }} 页
    </div>

    <!-- 图片上传进度 / 失败重试（fixed overlay） -->
    <Teleport to="body">
      <div
        v-if="uploading || uploadError"
        class="word-editor__upload-overlay"
      >
        <div class="word-editor__upload-card">
          <template v-if="uploading">
            <LoadingOutlined spin />
            <span class="word-editor__upload-text">图片上传中 {{ uploadProgress }}%</span>
            <a-progress
              :percent="uploadProgress"
              :show-info="false"
              size="small"
              class="word-editor__upload-progress"
            />
          </template>
          <template v-else>
            <span class="word-editor__upload-error">{{ uploadError }}</span>
            <a-button
              size="small"
              type="link"
              :disabled="!lastImageJob"
              @click="retryImageUpload"
            >
              重试
            </a-button>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditor：类 Word 富文本编辑区
 * - 外层灰色滚动区 + 居中 A4 白纸（深色模式下纸面强制白色，见样式注释）
 * - props：content(HTML)/readonly/placeholder/projectId；emit update:content
 * - 图片拖拽/粘贴上传：editorProps.handleDrop/handlePaste 拦截 image/* →
 *   useImageUpload 上传 → insertContent 插入；上传进度/失败 overlay
 * - 虚拟页码：按滚动位置与 A4 高度计算当前页/总页数
 * - defineExpose：getHTML/getJSON/getText/setContent/focus/editor
 */
import { ref, watch, onMounted, onBeforeUnmount, toRef, shallowRef } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import type { Editor } from '@tiptap/core'
import { Extension } from '@tiptap/core'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { LoadingOutlined } from '@ant-design/icons-vue'
import { createEditorExtensions } from './extensions'
import { useImageUpload } from '@/composables/useImageUpload'

interface AnnotationMark {
  id: string
  from: number
  to: number
  status: 'open' | 'resolved'
}

interface WordEditorProps {
  /** 初始内容（HTML 字符串）；外部变化时编辑器同步刷新 */
  content?: string
  /** 只读模式（禁止编辑） */
  readonly?: boolean
  /** 空文档占位提示文案 */
  placeholder?: string
  /** 项目 ID（用于图片上传，缺失时禁用拖拽/粘贴上传） */
  projectId?: string
  /** 批注选区标记（只读模式下高亮显示） */
  annotations?: AnnotationMark[]
  /** 当前激活的批注 ID（高亮显示） */
  activeAnnotationId?: string | null
}

const props = withDefaults(defineProps<WordEditorProps>(), {
  content: '',
  readonly: false,
  placeholder: '请输入内容...',
  projectId: undefined,
  annotations: () => [],
  activeAnnotationId: null,
})

const emit = defineEmits<{
  (e: 'update:content', value: string): void
  (e: 'selection-change', selection: { from: number; to: number; text: string } | null): void
}>()

/* ---------------- 图片上传 ---------------- */
const projectIdRef = toRef(props, 'projectId')
const {
  uploadImage,
  uploading,
  uploadProgress,
  error: uploadError,
  clearError,
} = useImageUpload(projectIdRef)

/**
 * 编辑器实例延迟句柄：editorProps 中的异步回调（上传完成后插入）通过此句柄
 * 访问编辑器，避免在 useEditor 初始化阶段引用未声明的 editor 绑定（TDZ）。
 */
const editorInstance = shallowRef<Editor | undefined>(undefined)

/** 最近一次失败的图片上传任务（供「重试」使用） */
const lastImageJob = ref<{ files: File[]; pos?: number } | null>(null)

/** 从 DataTransfer 中提取图片文件 */
const imageFilesFromTransfer = (dt: DataTransfer | null | undefined): File[] => {
  if (!dt) return []
  return Array.from(dt.files ?? []).filter((f) => f.type.startsWith('image/'))
}

/** 上传并插入图片：逐个上传，全部失败时记录任务供重试 */
const handleImageFiles = async (files: File[], pos?: number) => {
  const urls: string[] = []
  for (const file of files) {
    try {
      urls.push(await uploadImage(file))
    } catch {
      // 错误已写入 uploadError
    }
  }
  if (urls.length === 0) {
    lastImageJob.value = { files, pos }
    return
  }
  lastImageJob.value = null
  const inst = editorInstance.value
  if (!inst || inst.isDestroyed) return
  const content = urls.map((u) => ({ type: 'image', attrs: { src: u } }))
  if (typeof pos === 'number') {
    inst.chain().focus().insertContentAt(pos, content).run()
  } else {
    inst.chain().focus().insertContent(content).run()
  }
}

/** 重试上一次失败的图片上传 */
const retryImageUpload = () => {
  const job = lastImageJob.value
  if (!job) return
  clearError()
  void handleImageFiles(job.files, job.pos)
}

/* ---------------- 编辑器 ---------------- */

/** 批注高亮 decorations 的外部数据源（shallowRef 避免深响应） */
const annotationMarks = shallowRef<AnnotationMark[]>([])
// 本地激活态；与 props.activeAnnotationId 同名字段区分，避免遮蔽 props 访问
const localActiveAnnotationId = ref<string | null>(null)

watch(() => props.annotations, (val) => { annotationMarks.value = val || [] }, { immediate: true })
watch(() => props.activeAnnotationId, (val) => { localActiveAnnotationId.value = val })

/** 批注高亮扩展：根据 annotationMarks 生成 inline decorations */
const annotationKey = new PluginKey('annotationHighlight')
const AnnotationHighlight = Extension.create({
  name: 'annotationHighlight',
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: annotationKey,
        props: {
          decorations: (state) => {
            const marks = annotationMarks.value
            if (!marks || marks.length === 0) return DecorationSet.empty
            const docSize = state.doc.content.size
            const decos = marks
              .filter((m) => m.from < docSize && m.to <= docSize && m.from < m.to)
              .map((m) =>
                Decoration.inline(m.from, m.to, {
                  class: `annotation-mark annotation-mark--${m.status}${
                    localActiveAnnotationId.value === m.id ? ' annotation-mark--active' : ''
                  }`,
                  'data-annotation-id': m.id,
                }),
              )
            return DecorationSet.create(state.doc, decos)
          },
        },
      }),
    ]
  },
})

const editor = useEditor({
  extensions: [...createEditorExtensions({ placeholder: props.placeholder }), AnnotationHighlight],
  content: props.content,
  editable: !props.readonly,
  editorProps: {
    attributes: {
      class: 'word-editor__prosemirror',
      'aria-label': '富文本编辑区',
    },
    // 拖拽图片 → 上传后插入到落点位置
    handleDrop: (view, event) => {
      const files = imageFilesFromTransfer(event.dataTransfer)
      if (!files.length || !props.projectId) return false
      const pos = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos ?? undefined
      void handleImageFiles(files, pos)
      return true
    },
    // 粘贴图片 → 上传后插入到当前选区
    handlePaste: (_view, event) => {
      const files = imageFilesFromTransfer(event.clipboardData)
      if (!files.length || !props.projectId) return false
      void handleImageFiles(files)
      return true
    },
  },
  onUpdate: ({ editor: instance }) => {
    emit('update:content', instance.getHTML())
  },
  onSelectionUpdate: ({ editor: instance }) => {
    if (props.readonly) {
      const { from, to } = instance.state.selection
      if (from !== to) {
        const text = instance.state.doc.textBetween(from, to, ' ')
        emit('selection-change', { from, to, text })
      } else {
        emit('selection-change', null)
      }
    }
  },
})

// 编辑器就绪后绑定句柄，供异步回调使用
watch(
  editor,
  (e) => {
    editorInstance.value = e ?? undefined
  },
  { immediate: true },
)

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

// 批注数据变化 → 触发 decorations 重绘
watch(
  [() => props.annotations, () => props.activeAnnotationId],
  () => {
    const view = editor.value?.view
    if (view) {
      view.dispatch(view.state.tr.setMeta(annotationKey, {}))
    }
  },
  { deep: true },
)

/* ---------------- 虚拟页码 ---------------- */
const scrollRef = ref<HTMLElement | null>(null)
const paperRef = ref<HTMLElement | null>(null)
const currentPage = ref(1)
const totalPages = ref(1)

/** A4 高度（px）：1mm = 96/25.4 px */
const PAGE_HEIGHT_PX = 297 * (96 / 25.4)

/** 根据滚动位置与纸面高度重算当前页/总页数 */
const recomputePages = () => {
  const scroll = scrollRef.value
  const paper = paperRef.value
  if (!scroll || !paper) {
    currentPage.value = 1
    totalPages.value = 1
    return
  }
  const total = Math.max(1, Math.ceil(paper.scrollHeight / PAGE_HEIGHT_PX))
  totalPages.value = total
  // 以视口垂直中心所在「页带」作为当前页
  const viewportCenter = scroll.scrollTop + scroll.clientHeight / 2
  const relToPaper = viewportCenter - paper.offsetTop
  let page = Math.floor(relToPaper / PAGE_HEIGHT_PX) + 1
  page = Math.min(Math.max(page, 1), total)
  currentPage.value = page
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  const scroll = scrollRef.value
  scroll?.addEventListener('scroll', recomputePages, { passive: true })
  const paper = paperRef.value
  if (paper && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => recomputePages())
    resizeObserver.observe(paper)
  }
  recomputePages()
})

onBeforeUnmount(() => {
  scrollRef.value?.removeEventListener('scroll', recomputePages)
  resizeObserver?.disconnect()
})

/* ---------------- 对外方法 ---------------- */
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

/** 滚动到指定文档位置 */
const scrollToPosition = (pos: number): void => {
  const instance = editor.value
  if (!instance) return
  const coords = instance.view.coordsAtPos(Math.min(pos, instance.state.doc.content.size))
  const scrollEl = instance.view.dom.closest('.word-editor__scroll') as HTMLElement | null
  if (scrollEl) {
    const containerRect = scrollEl.getBoundingClientRect()
    const offset = coords.top - containerRect.top + scrollEl.scrollTop - 100
    scrollEl.scrollTo({ top: offset, behavior: 'smooth' })
  }
}

/** 获取当前选区信息 */
const getSelectionInfo = (): { from: number; to: number; text: string } | null => {
  const instance = editor.value
  if (!instance) return null
  const { from, to } = instance.state.selection
  if (from === to) return null
  return { from, to, text: instance.state.doc.textBetween(from, to, ' ') }
}

defineExpose({
  editor,
  getHTML,
  getJSON,
  getText,
  setContent,
  focus,
  scrollToPosition,
  getSelectionInfo,
})
</script>

<style scoped>
.word-editor {
  position: relative;
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
  width: var(--paper-width, 210mm);
  min-height: var(--paper-height, 297mm);
  padding: var(--paper-padding, 25.4mm);
  box-sizing: border-box;
  background: #ffffff; /* 纸面恒白，不随主题变化 */
  color: #1f2329; /* 纸面文字恒深色，保证白纸可读性 */
  box-shadow: var(--shadow-md);
  transform: scale(var(--paper-zoom, 1));
  transform-origin: top center;
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
/* 可调宽表格的容器：横向滚动，避免撑破纸面 */
.word-editor :deep(.word-editor__prosemirror .tableWrapper) {
  overflow-x: auto;
}
.word-editor :deep(.word-editor__prosemirror th),
.word-editor :deep(.word-editor__prosemirror td) {
  border: 1px solid #dee0e3;
  padding: 6px 8px;
  vertical-align: top;
  min-width: 1em;
  position: relative;
}
.word-editor :deep(.word-editor__prosemirror th) {
  background: #f5f6f7; /* 纸面表头底色 */
  font-weight: 600;
}
/* 选中单元格高亮：::after 半透明主色覆盖层（纸面字面量，保证深浅一致） */
.word-editor :deep(.word-editor__prosemirror .selectedCell::after) {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(59, 130, 246, 0.1);
  pointer-events: none;
  z-index: 0;
}
/* 列宽拖拽手柄：纸面主色细条 */
.word-editor :deep(.word-editor__prosemirror .column-resize-handle) {
  position: absolute;
  right: -2px;
  top: 0;
  bottom: 0;
  width: 4px;
  background: #3370ff;
  cursor: col-resize;
  z-index: 10;
}

/* 分页符：虚线 + "分页符" 文字，打印时 page-break-after 生效 */
.word-editor :deep(.word-editor__prosemirror .page-break) {
  border-top: 2px dashed #dee0e3;
  margin: 2em 0;
  page-break-after: always;
  break-after: page;
  position: relative;
  height: 0;
}
.word-editor :deep(.word-editor__prosemirror .page-break::after) {
  content: '分页符';
  position: absolute;
  top: -11px;
  left: 50%;
  transform: translateX(-50%);
  background: #ffffff;
  color: #8f959e;
  font-size: 12px;
  padding: 0 8px;
  line-height: 1;
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

/* ---------- 虚拟页码（编辑区右下角） ---------- */
.word-editor__page-number {
  position: absolute;
  right: 16px;
  bottom: 12px;
  z-index: 5;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  padding: 2px 8px;
  pointer-events: none;
}

/* ---------- 图片上传进度/错误 overlay ---------- */
.word-editor__upload-overlay {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1100;
}
.word-editor__upload-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--space-2) var(--space-3);
}
.word-editor__upload-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  white-space: nowrap;
}
.word-editor__upload-progress {
  width: 160px;
}
.word-editor__upload-error {
  font-size: var(--font-size-sm);
  color: var(--color-error);
}

/* 批注高亮标记 */
.word-editor :deep(.annotation-mark) {
  border-radius: 2px;
  padding: 1px 0;
  cursor: pointer;
  transition: background-color 0.2s;
}
.word-editor :deep(.annotation-mark--open) {
  background-color: rgba(250, 173, 20, 0.25);
  border-bottom: 2px solid #faad14;
}
.word-editor :deep(.annotation-mark--resolved) {
  background-color: rgba(82, 196, 26, 0.15);
  border-bottom: 2px solid #52c41a;
  opacity: 0.7;
}
.word-editor :deep(.annotation-mark--active) {
  background-color: rgba(24, 144, 255, 0.3) !important;
  border-bottom: 2px solid #1890ff !important;
  box-shadow: 0 0 0 1px rgba(24, 144, 255, 0.5);
}
</style>
