<template>
  <div class="word-page">
    <!-- 顶栏：返回 + 章节信息 + 保存 -->
    <header class="word-page__header">
      <div class="word-page__header-left">
        <a-button
          size="small"
          aria-label="返回分工页"
          @click="handleBack"
        >
          <template #icon>
            <ArrowLeftOutlined />
          </template>
          返回
        </a-button>
        <a-divider type="vertical" />
        <a-tag color="blue">
          {{ chapterNo }}
        </a-tag>
        <span class="word-page__chapter-title">{{ chapterTitle || '章节编辑' }}</span>
      </div>
      <div class="word-page__header-right">
        <span
          class="word-page__save-hint"
          :class="`word-page__save-hint--${saveStatus}`"
        >
          {{ saveHint }}
        </span>
        <a-button
          size="small"
          type="primary"
          :loading="saveStatus === 'saving'"
          aria-label="保存章节内容"
          @click="saveNow"
        >
          保存
        </a-button>
      </div>
    </header>

    <!-- Ribbon 工具栏（a-tabs 四选项卡） -->
    <WordEditorToolbar
      class="word-page__toolbar"
      :editor="editorInstance"
      :project-id="projectId"
      :upload-image="uploadImage"
      @update:outline-visible="outlineVisible = $event"
      @update:zoom="zoom = $event"
    />

    <!-- 主体：三栏布局 -->
    <div class="word-page__body">
      <!-- 左侧：大纲导航面板 -->
      <WordEditorOutline
        v-model:visible="outlineVisible"
        :editor="editorInstance"
      />

      <!-- 中间：A4 纸面编辑区 + 浮动组件 -->
      <div class="word-page__editor-area">
        <a-spin
          :spinning="loading"
          wrapper-class-name="word-page__editor-spin"
        >
          <WordEditor
            ref="editorRef"
            class="word-page__editor"
            :content="initialHtml"
            :readonly="loading"
            :project-id="projectId"
            :style="{ '--paper-zoom': zoom / 100 }"
            placeholder="请输入章节内容，支持标题、列表、表格等富文本排版..."
            @update:content="handleContentUpdate"
          />
        </a-spin>

        <!-- 查找替换浮动面板 -->
        <WordEditorSearchPanel
          v-model:visible="searchVisible"
          v-model:mode="searchMode"
          :editor="editorInstance"
          :initial-query="searchQuery"
        />

        <!-- 表格浮动工具栏（组件内 v-if 自行控制显隐） -->
        <div class="word-page__table-toolbar-wrapper">
          <WordEditorTableToolbar :editor="editorInstance" />
        </div>

        <!-- 图片浮动工具栏（position: fixed 自行定位） -->
        <WordEditorImageToolbar
          :editor="editorInstance"
          :upload-image="uploadImage"
        />

        <!-- 右键菜单（自行挂 contextmenu 事件到 editor.view.dom） -->
        <WordEditorContextMenu
          :editor="editorInstance"
          @insert-image="triggerImageUpload"
          @insert-link="triggerLinkInsert"
          @find="openFindFromText"
        />
      </div>

      <!-- 右侧：属性面板（P2 预留，暂不渲染） -->
    </div>

    <!-- 底部状态栏 -->
    <WordEditorStatusBar
      :editor="editorInstance"
      :save-status="saveStatus"
      :zoom="zoom"
      @update:zoom="zoom = $event"
    />

    <!-- 图片上传进度 overlay（Teleport 到 body） -->
    <Teleport to="body">
      <div
        v-if="uploading"
        class="word-page__upload-overlay"
      >
        <div class="word-page__upload-card">
          <LoadingOutlined spin />
          <span class="word-page__upload-text">图片上传中 {{ uploadProgress }}%</span>
          <a-progress
            :percent="uploadProgress"
            :show-info="false"
            size="small"
            class="word-page__upload-progress"
          />
        </div>
      </div>
    </Teleport>

    <!-- 链接插入弹窗 -->
    <a-modal
      v-model:open="linkModalOpen"
      title="插入链接"
      ok-text="插入"
      cancel-text="取消"
      @ok="confirmLinkInsert"
    >
      <a-input
        v-model:value="linkUrl"
        placeholder="请输入链接地址（如 https://example.com）"
        allow-clear
        @keydown.enter.prevent="confirmLinkInsert"
      />
    </a-modal>

    <!-- 隐藏文件选择 input（右键菜单"插入图片"触发） -->
    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      class="word-page__file-input"
      @change="handleFileSelect"
    >
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorPage：章节全屏富文本编辑页（P1 批 C：快捷键系统 + 全组件集成）
 *
 * 路由：/project/:projectId/editor/:chapterNo
 *
 * 布局：Header → Ribbon Toolbar → [Outline | Editor Area | (P2)] → StatusBar
 *
 * 数据流：
 * - 加载：fetchChapterContent → content_html 优先，否则 markdownToHtml(content)
 * - 保存：htmlToMarkdown(getHTML()) 得 markdown，连同 HTML 双字段 PUT 保存
 * - 自动保存：内容变化 2s 防抖；失败自动重试 2 次；Ctrl+S 手动保存；
 *   beforeunload 拦截未保存离开
 *
 * 快捷键系统（useHotkeys）：
 * - Ctrl+S 保存、Ctrl+F/H 查找替换、Ctrl+L/E/R/J 对齐、Ctrl+1/2/3 行高
 * - Ctrl+Shift+>/< 增减字号、Ctrl+Shift+C/V 格式刷、Alt+Shift+←/→ 标题级别
 * - Ctrl+Enter 分页符、Escape 关闭面板/取消格式刷
 *
 * 组件集成：
 * - Outline（v-model:visible）、SearchPanel（v-model:visible/mode）
 * - TableToolbar / ImageToolbar（自行显示/隐藏）
 * - ContextMenu（自行挂 contextmenu 事件）
 * - Toolbar 传入 projectId/uploadImage 并监听 outlineVisible/zoom
 * - StatusBar 传入 zoom 并监听 update:zoom
 */
import { ref, computed, unref, shallowRef, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined, LoadingOutlined } from '@ant-design/icons-vue'
import type { Editor } from '@tiptap/core'
import WordEditor from './WordEditor.vue'
import WordEditorToolbar from './WordEditorToolbar.vue'
import WordEditorStatusBar from './WordEditorStatusBar.vue'
import WordEditorOutline from './WordEditorOutline.vue'
import WordEditorSearchPanel from './WordEditorSearchPanel.vue'
import WordEditorTableToolbar from './WordEditorTableToolbar.vue'
import WordEditorImageToolbar from './WordEditorImageToolbar.vue'
import WordEditorContextMenu from './WordEditorContextMenu.vue'
import type { SaveStatus } from './WordEditorStatusBar.vue'
import { markdownToHtml, htmlToMarkdown } from './utils/markdown-converter'
import {
  fetchChapterContent,
  saveChapterContent,
  fetchChapterAssignments,
} from '@/api'
import type { AssignmentNode } from '@/types'
import { useHotkeys } from '@/composables/useHotkeys'
import { useImageUpload } from '@/composables/useImageUpload'
import { useFormatBrush } from '@/composables/useFormatBrush'
import { FONT_SIZE_OPTIONS } from './extensions/font-size'
import { provide } from 'vue'

/* ---------------- 路由参数 ---------------- */
const route = useRoute()
const router = useRouter()
const projectId = String(route.params.projectId ?? '')
const chapterNo = String(route.params.chapterNo ?? '')

/* ---------------- 编辑器实例 ---------------- */
const editorRef = ref<InstanceType<typeof WordEditor> | null>(null)
/** 编辑器实例（透传给工具栏/状态栏等子组件，auto-unwrap 为 Editor | undefined） */
const editorInstance = computed(() => unref(editorRef.value?.editor))

/**
 * 编辑器实例的 ShallowRef 副本，供 useFormatBrush 等 composable 使用。
 * ComputedRef 不可直接赋给 Ref<Editor | undefined> 参数，故通过 watch 同步。
 */
const editorForComposables = shallowRef<Editor | undefined>(undefined)
watch(
  editorInstance,
  (val) => {
    editorForComposables.value = val
  },
  { immediate: true },
)

/* ---------------- 加载 / 保存状态 ---------------- */
const loading = ref(false)
const initialHtml = ref('')
const chapterTitle = ref('')

/** 保存状态机：idle → saving → saved/error */
const saveStatus = ref<SaveStatus>('idle')
/** 是否有未保存改动（对比最近一次成功保存的 HTML） */
const dirty = ref(false)
const lastSavedHtml = ref('')
/** 自动保存失败重试计数（上限 2 次） */
const retryCount = ref(0)

/* 定时器句柄 */
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null

/** 自动保存防抖时长（ms） */
const AUTOSAVE_DEBOUNCE_MS = 2000
/** 失败重试延迟（ms） */
const RETRY_DELAY_MS = 1500
/** 自动保存最大重试次数 */
const MAX_RETRY = 2

const SAVE_HINT: Record<SaveStatus, string> = {
  idle: '有改动未保存时将自动保存',
  saving: '保存中...',
  saved: '已保存',
  error: '保存失败，自动重试中...',
}
const saveHint = computed(() =>
  dirty.value && saveStatus.value === 'idle' ? '待自动保存' : SAVE_HINT[saveStatus.value],
)

/* ---------------- 内容变化 → 防抖自动保存 ---------------- */
const handleContentUpdate = (html: string) => {
  dirty.value = html !== lastSavedHtml.value
  if (!dirty.value) {
    // 内容回退到上次保存状态：取消待执行的自动保存
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer)
      autoSaveTimer = null
    }
    return
  }
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => {
    void doSave('auto')
  }, AUTOSAVE_DEBOUNCE_MS)
}

/* ---------------- 保存核心逻辑 ---------------- */
/**
 * 执行保存：getHTML → htmlToMarkdown 得 markdown，双字段提交。
 * @param source auto=自动保存（静默失败重试）；manual=手动保存（结果有提示）
 */
const doSave = async (source: 'auto' | 'manual') => {
  const instance = editorRef.value
  if (!instance || loading.value || saveStatus.value === 'saving') return
  if (!dirty.value && source === 'auto') return

  saveStatus.value = 'saving'
  try {
    const html = instance.getHTML()
    const markdown = htmlToMarkdown(html)
    await saveChapterContent(projectId, chapterNo, {
      content: markdown,
      content_html: html,
    })
    lastSavedHtml.value = html
    dirty.value = false
    retryCount.value = 0
    saveStatus.value = 'saved'
    if (source === 'manual') {
      message.success('保存成功')
    }
  } catch {
    saveStatus.value = 'error'
    if (retryCount.value < MAX_RETRY) {
      // 自动重试：延迟后重新触发
      retryCount.value++
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = setTimeout(() => {
        void doSave(source)
      }, RETRY_DELAY_MS)
    } else if (source === 'manual') {
      message.error('保存失败，请稍后重试')
    }
  }
}

/** 手动保存（Ctrl+S / 保存按钮）：先清掉待执行的自动保存 */
const saveNow = () => {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
  void doSave('manual')
}

/* ---------------- 面板显隐 / 缩放 / 弹窗状态 ---------------- */
/** 大纲面板显隐（默认 false：P0 用户习惯先看不到，从「视图」选项卡切换） */
const outlineVisible = ref(false)
/** 查找替换面板显隐 */
const searchVisible = ref(false)
/** 查找替换面板模式 */
const searchMode = ref<'find' | 'replace'>('find')
/** 缩放百分比（传给 WordEditor CSS 变量与 StatusBar） */
const zoom = ref(100)
/** 链接插入弹窗显隐 */
const linkModalOpen = ref(false)
/** 链接 URL 输入值 */
const linkUrl = ref('')
/** 隐藏文件选择 input 的 ref */
const fileInputRef = ref<HTMLInputElement | null>(null)
/** 搜索查询（右键菜单"查找"选中文字 → 通过 initial-query 传给 SearchPanel） */
const searchQuery = ref('')

/* ---------------- 图片上传 composable ---------------- */
const { uploadImage, uploadProgress, uploading } = useImageUpload(
  ref<string | undefined>(projectId),
)

/* ---------------- 格式刷 composable（单一实例，provide 给 Toolbar） ---------------- */
const formatBrush = useFormatBrush(editorForComposables)
provide('formatBrush', formatBrush)

/* ---------------- 字号增减 ---------------- */

/**
 * 增大字号：在 FONT_SIZE_OPTIONS（从大到小排列）中找到当前字号，
 * 取上一个（更大）的 value 调用 setFontSize。
 */
const increaseFontSize = () => {
  const ed = editorInstance.value
  if (!ed) return
  const current = ed.getAttributes('textStyle').fontSize as string | null | undefined
  const idx = current
    ? FONT_SIZE_OPTIONS.findIndex((o) => o.value === current)
    : -1
  if (idx === -1) {
    // 当前字号不在预设中：取首个大于当前 px 的选项
    const currentPx = current ? parseFloat(current) : 14
    const next = FONT_SIZE_OPTIONS.find((o) => parseFloat(o.value) > currentPx)
    if (next) ed.chain().focus().setFontSize(next.value).run()
    return
  }
  if (idx > 0) {
    ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[idx - 1].value).run()
  }
}

/**
 * 减小字号：在 FONT_SIZE_OPTIONS 中取下一个（更小）的 value。
 */
const decreaseFontSize = () => {
  const ed = editorInstance.value
  if (!ed) return
  const current = ed.getAttributes('textStyle').fontSize as string | null | undefined
  const idx = current
    ? FONT_SIZE_OPTIONS.findIndex((o) => o.value === current)
    : -1
  if (idx === -1) {
    const currentPx = current ? parseFloat(current) : 14
    for (let i = FONT_SIZE_OPTIONS.length - 1; i >= 0; i--) {
      if (parseFloat(FONT_SIZE_OPTIONS[i].value) < currentPx) {
        ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[i].value).run()
        return
      }
    }
    return
  }
  if (idx < FONT_SIZE_OPTIONS.length - 1) {
    ed.chain().focus().setFontSize(FONT_SIZE_OPTIONS[idx + 1].value).run()
  }
}

/* ---------------- 快捷键系统 ---------------- */
useHotkeys([
  // 保存（已有）
  { combo: 'ctrl+s', allowInInput: true, handler: saveNow },
  // 查找 / 替换
  {
    combo: 'ctrl+f',
    allowInInput: true,
    handler: () => {
      searchMode.value = 'find'
      searchVisible.value = true
    },
  },
  {
    combo: 'ctrl+h',
    allowInInput: true,
    handler: () => {
      searchMode.value = 'replace'
      searchVisible.value = true
    },
  },
  // 对齐
  {
    combo: 'ctrl+l',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setTextAlign('left').run(),
  },
  {
    combo: 'ctrl+e',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setTextAlign('center').run(),
  },
  {
    combo: 'ctrl+r',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setTextAlign('right').run(),
  },
  {
    combo: 'ctrl+j',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setTextAlign('justify').run(),
  },
  // 行高
  {
    combo: 'ctrl+1',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setLineHeight('1').run(),
  },
  {
    combo: 'ctrl+2',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setLineHeight('1.5').run(),
  },
  {
    combo: 'ctrl+3',
    allowInInput: true,
    handler: () => editorInstance.value?.chain().focus().setLineHeight('2').run(),
  },
  // 字号增减（Shift+. → '>'，Shift+, → '<'）
  {
    combo: 'ctrl+shift+>',
    allowInInput: true,
    handler: increaseFontSize,
  },
  {
    combo: 'ctrl+shift+<',
    allowInInput: true,
    handler: decreaseFontSize,
  },
  // 格式刷
  {
    combo: 'ctrl+shift+c',
    allowInInput: true,
    handler: () => formatBrush.copyFormat('continuous'),
  },
  {
    combo: 'ctrl+shift+v',
    allowInInput: true,
    handler: () => formatBrush.applyFormat(),
  },
  // 标题级别：Alt+Shift+← 降低（增大 level 数值），Alt+Shift+→ 提升
  {
    combo: 'alt+shift+arrowleft',
    allowInInput: true,
    handler: () => {
      const ed = editorInstance.value
      if (!ed) return
      if (ed.isActive('heading', { level: 4 })) {
        ed.chain().focus().setParagraph().run()
      } else if (ed.isActive('heading')) {
        const lvl = ed.getAttributes('heading').level as number
        ed.chain().focus().setHeading({ level: (lvl + 1) as 1 | 2 | 3 | 4 }).run()
      } else {
        ed.chain().focus().setHeading({ level: 1 }).run()
      }
    },
  },
  {
    combo: 'alt+shift+arrowright',
    allowInInput: true,
    handler: () => {
      const ed = editorInstance.value
      if (!ed) return
      if (ed.isActive('heading', { level: 1 })) {
        ed.chain().focus().setParagraph().run()
      } else if (ed.isActive('heading')) {
        const lvl = ed.getAttributes('heading').level as number
        if (lvl > 1) {
          ed.chain().focus().setHeading({ level: (lvl - 1) as 1 | 2 | 3 | 4 }).run()
        }
      } else {
        ed.chain().focus().setHeading({ level: 4 }).run()
      }
    },
  },
  // 分页符（Tiptap page-break 扩展已处理 Mod-Enter，此处仅在编辑器外触发）
  {
    combo: 'ctrl+enter',
    allowInInput: true,
    handler: (e: KeyboardEvent) => {
      // 当事件源自 contenteditable 编辑区时，Tiptap 已处理 Mod-Enter，
      // 跳过以避免重复插入分页符
      const target = e.target
      if (target instanceof HTMLElement && target.isContentEditable) return
      editorInstance.value?.chain().focus().setPageBreak().run()
    },
  },
  // Escape：依次关闭搜索面板 / 取消格式刷
  {
    combo: 'escape',
    allowInInput: true,
    handler: () => {
      if (searchVisible.value) {
        searchVisible.value = false
      } else if (formatBrush.brushActive.value) {
        formatBrush.cancelBrush()
      }
    },
  },
])

/* ---------------- 右键菜单事件处理 ---------------- */

/**
 * 触发隐藏 input[type=file] → 用户选择图片 → uploadImage → setImage。
 */
const triggerImageUpload = () => {
  fileInputRef.value?.click()
}

/** 文件选择 input change 事件：上传并插入图片 */
const handleFileSelect = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const url = await uploadImage(file)
    editorInstance.value?.chain().focus().setImage({ src: url }).run()
  } catch {
    message.error('图片上传失败')
  } finally {
    // 重置 input value 以允许重复选择同一文件
    input.value = ''
  }
}

/**
 * 插入链接：弹出 a-modal 输入 URL → setLink。
 */
const triggerLinkInsert = () => {
  linkUrl.value = ''
  linkModalOpen.value = true
}

/** 链接弹窗确认：将输入 URL 设为当前选区链接 */
const confirmLinkInsert = () => {
  const url = linkUrl.value.trim()
  if (url) {
    editorInstance.value?.chain().focus().setLink({ href: url }).run()
  }
  linkModalOpen.value = false
}

/**
 * 右键菜单"查找"：接收选中文本，设入 searchQuery 并打开面板。
 * SearchPanel 通过 initial-query prop 接收并自动搜索。
 */
const openFindFromText = (text: string) => {
  searchQuery.value = text
  searchMode.value = 'find'
  searchVisible.value = true
}

/* ---------------- 格式刷编辑区 click 绑定 ---------------- */

/**
 * 格式刷激活时编辑区 click → applyFormat。
 * 通过 watch brushActive 给 editor.view.dom 挂/卸 click listener，
 * 避免修改 WordEditor.vue 内部 editorProps.handleClick。
 */
const onBrushClick = () => {
  formatBrush.applyFormat()
}

/** brushActive 变化 → 挂/卸 click listener */
watch(formatBrush.brushActive, (active) => {
  const inst = editorForComposables.value
  if (!inst || inst.isDestroyed) return
  const dom = inst.view.dom
  if (active) {
    dom.addEventListener('click', onBrushClick)
  } else {
    dom.removeEventListener('click', onBrushClick)
  }
})

/** 编辑器实例变化 → 迁移 click listener */
watch(editorForComposables, (inst, oldInst) => {
  if (oldInst && !oldInst.isDestroyed) {
    oldInst.view.dom.removeEventListener('click', onBrushClick)
  }
  if (inst && !inst.isDestroyed && formatBrush.brushActive.value) {
    inst.view.dom.addEventListener('click', onBrushClick)
  }
})

/* ---------------- 数据加载 ---------------- */

/** 在分工树中递归查找 chapter_no 对应的标题 */
const findChapterTitle = (nodes: AssignmentNode[], target: string): string => {
  for (const node of nodes) {
    if (node.chapter_no === target) return node.title
    if (node.children?.length) {
      const found = findChapterTitle(node.children, target)
      if (found) return found
    }
  }
  return ''
}

const loadChapter = async () => {
  loading.value = true
  try {
    const [contentRes, assignmentsRes] = await Promise.all([
      fetchChapterContent(projectId, chapterNo),
      fetchChapterAssignments(projectId),
    ])
    const data = contentRes.data.data
    // content_html 优先；缺失时将 markdown 转 HTML 供富文本编辑
    initialHtml.value = data?.content_html || (data?.content ? markdownToHtml(data.content) : '')
    lastSavedHtml.value = initialHtml.value
    chapterTitle.value = findChapterTitle(assignmentsRes.data.data?.items ?? [], chapterNo)
  } catch {
    message.error('章节内容加载失败')
  } finally {
    loading.value = false
  }
}

/* ---------------- 返回 / 生命周期 ---------------- */
const handleBack = () => {
  void router.push({ name: 'Division', params: { projectId } })
}

/** 页面关闭/刷新时拦截未保存内容 */
const handleBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  void loadChapter()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (retryTimer) clearTimeout(retryTimer)
  // 移除格式刷 click listener
  const inst = editorForComposables.value
  if (inst && !inst.isDestroyed) {
    inst.view.dom.removeEventListener('click', onBrushClick)
  }
})
</script>

<style scoped>
/* ========== 页面容器 ========== */
.word-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-app);
}

/* ========== 顶栏 ========== */
.word-page__header {
  flex: 0 0 auto;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}

.word-page__header-left,
.word-page__header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.word-page__chapter-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-primary);
}

/* 保存状态提示 */
.word-page__save-hint {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}
.word-page__save-hint--saving {
  color: var(--color-primary);
}
.word-page__save-hint--saved {
  color: var(--color-success);
}
.word-page__save-hint--error {
  color: var(--color-error);
}

/* ========== 工具栏 ========== */
.word-page__toolbar {
  flex: 0 0 auto;
}

/* ========== 主体三栏布局 ========== */
.word-page__body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

/* 编辑区容器 */
.word-page__editor-area {
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  flex-direction: column;
}

/* spin 包裹层撑满 */
.word-page__editor-spin,
.word-page__editor-spin :deep(.ant-spin-container) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.word-page__editor {
  flex: 1;
  min-height: 0;
}

/* ========== 缩放：CSS 变量 → :deep 纸面 transform ========== */
/* 通过 WordEditor 的 :style 注入 --paper-zoom，:deep 应用 transform */
.word-page__editor :deep(.word-editor__paper) {
  transform: scale(var(--paper-zoom, 1));
  transform-origin: top center;
}

/* ========== 表格工具栏浮动定位 ========== */
.word-page__table-toolbar-wrapper {
  position: absolute;
  top: var(--space-2);
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
}

/* ========== 图片上传进度 overlay ========== */
.word-page__upload-overlay {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1100;
}
.word-page__upload-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--space-2) var(--space-3);
}
.word-page__upload-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  white-space: nowrap;
}
.word-page__upload-progress {
  width: 160px;
}

/* ========== 隐藏文件选择 input ========== */
.word-page__file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
</style>
