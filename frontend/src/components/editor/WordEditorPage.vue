<template>
  <div class="word-page">
    <!-- 顶栏：返回 + 章节信息 + 保存 + 导出/打印 + 视图切换 + 目录 + 面板开关 + AI 辅助 -->
    <!-- N7：抽为结构组件 WordEditorHeader（配套 CSS 一并下沉，避免父级 scoped 样式断链） -->
    <WordEditorHeader
      v-model:preview-mode="previewMode"
      :chapter-no="chapterNo"
      :chapter-title="chapterTitle"
      :task-status-text="taskStatusText"
      :task-status-color="taskStatusColor"
      :is-read-only="isReadOnly"
      :can-accept="canAccept"
      :accepting="accepting"
      :can-submit="canSubmit"
      :submitting-task="submittingTask"
      :save-hint="saveHint"
      :save-status="saveStatus"
      :properties-visible="propertiesVisible"
      :comments-visible="commentsVisible"
      :version-history-visible="versionHistoryVisible"
      :ai-loading="aiLoading"
      @back="handleBack"
      @accept="handleAccept"
      @submit="handleSubmit"
      @save="saveNow"
      @export-word="handleExportWord"
      @print="handlePrint"
      @insert-toc="handleInsertToc"
      @update-toc="handleUpdateToc"
      @toggle-properties="toggleProperties"
      @toggle-comments="toggleComments"
      @toggle-version-history="toggleVersionHistory"
      @ai-action="handleAiAction"
      @auto-format="handleAutoFormat"
    />

    <!-- Ribbon 工具栏（只读 / 分页预览模式下隐藏） -->
    <WordEditorToolbar
      v-if="!isReadOnly && !previewMode"
      class="word-page__toolbar"
      :editor="editorInstance"
      :project-id="projectId"
      :upload-image="uploadImage"
      @update:outline-visible="outlineVisible = $event"
      @update:zoom="zoom = $event"
      @open-comments="toggleComments"
    />

    <!-- 主体：三栏布局 -->
    <div class="word-page__body">
      <!-- 左侧：目录/大纲切换面板 -->
      <div
        v-if="leftPanelVisible"
        class="word-page__left-panel"
      >
        <div class="word-page__left-tabs">
          <div
            class="word-page__left-tab"
            :class="{ 'word-page__left-tab--active': leftPanelTab === 'navigator' }"
            @click="leftPanelTab = 'navigator'"
          >
            目录
          </div>
          <div
            class="word-page__left-tab"
            :class="{ 'word-page__left-tab--active': leftPanelTab === 'outline' }"
            @click="leftPanelTab = 'outline'"
          >
            大纲
          </div>
          <a-button
            size="small"
            type="text"
            class="word-page__left-close"
            @click="leftPanelVisible = false"
          >
            <template #icon>
              <CloseOutlined />
            </template>
          </a-button>
        </div>
        <div class="word-page__left-content">
          <ChapterNavigator
            v-if="leftPanelTab === 'navigator'"
            :project-id="projectId"
            :current-chapter-no="chapterNo"
            @navigate="handleChapterNavigate"
          />
          <WordEditorOutline
            v-else
            v-model:visible="outlineVisible"
            :editor="editorInstance"
          />
        </div>
      </div>
      <!-- 左侧面板关闭时的展开按钮 -->
      <div
        v-else
        class="word-page__left-expand"
        @click="leftPanelVisible = true"
      >
        <MenuUnfoldOutlined />
      </div>

      <!-- 中间：A4 纸面编辑区 + 浮动组件 -->
      <div class="word-page__editor-area">
        <!-- 权限状态提示横幅 -->
        <a-alert
          v-if="!loading && permissionHint.text"
          :type="permissionHint.type"
          :message="permissionHint.text"
          show-icon
          class="word-page__permission-hint"
        />
        <!-- 水平标尺（视图选项卡控制显隐；分页预览隐藏） -->
        <WordEditorRuler
          v-if="rulerVisible && !previewMode"
          class="word-page__ruler"
          :editor="editorInstance"
          @indent-change="handleRulerIndentChange"
        />
        <!-- 连页编辑：A4 连续长纸（分页预览时隐藏但保持实例，未保存内容不丢失） -->
        <a-spin
          v-show="!previewMode"
          :spinning="loading"
          wrapper-class-name="word-page__editor-spin"
        >
          <WordEditor
            ref="editorRef"
            class="word-page__editor"
            :content="initialContent"
            :readonly="loading || isReadOnly"
            :project-id="projectId"
            :style="{ '--paper-zoom': zoom / 100 }"
            placeholder="请输入章节内容，支持标题、列表、表格等富文本排版..."
            @update:content="handleContentUpdate"
          />
        </a-spin>
        <!-- 分页预览：按 A4 逐页切分展示（Word 观感：页间留白 + 页码） -->
        <PaginatedPreview
          v-show="previewMode"
          class="word-page__preview"
          :html="previewHtml"
        />
        <!-- AI 辅助编写（只读模式隐藏；分页预览时隐藏输入区） -->
        <div
          v-if="!isReadOnly"
          v-show="!previewMode"
          class="word-page__assist"
        >
          <a-input
            v-model:value="assistPrompt"
            placeholder="输入 AI 辅助指令（章节负责人可用），如：补充技术架构说明、优化语言表达..."
            allow-clear
            :disabled="!canEdit || !isAssignee"
            @press-enter="handleAssist"
          >
            <template #addonAfter>
              <a-button
                type="primary"
                :loading="assisting"
                :disabled="!canEdit || !isAssignee"
                @click="handleAssist"
              >
                AI 辅助
              </a-button>
            </template>
          </a-input>
          <a-radio-group
            v-model:value="assistMode"
            size="small"
            :disabled="!canEdit || !isAssignee"
          >
            <a-radio-button value="append">
              追加
            </a-radio-button>
            <a-radio-button value="overwrite">
              覆盖
            </a-radio-button>
          </a-radio-group>
        </div>

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
          :editable="canEdit"
          @insert-image="triggerImageUpload"
          @insert-link="triggerLinkInsert"
          @find="openFindFromText"
          @ai-action="handleContextAi"
        />
      </div>

      <!-- 右侧：属性面板 -->
      <WordEditorProperties
        v-if="propertiesVisible"
        class="word-page__properties"
        :editor="editorInstance"
        @close="propertiesVisible = false"
      />

      <!-- 右侧：批注面板（2026-09-03 后端同源：与审阅页共享 chapter_annotations） -->
      <WordEditorComments
        v-if="commentsVisible"
        class="word-page__comments"
        :editor="editorInstance"
        :project-id="projectId"
        :chapter-no="chapterNo"
        @close="commentsVisible = false"
      />

      <!-- 右侧：版本历史面板 -->
      <WordEditorVersionHistory
        v-if="versionHistoryVisible"
        class="word-page__version"
        :editor="editorInstance"
        @close="versionHistoryVisible = false"
        @restore="handleRestoreVersion"
      />
    </div>

    <!-- 底部状态栏（分页预览模式隐藏） -->
    <WordEditorStatusBar
      v-show="!previewMode"
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
 * 快捷键系统（useEditorHotkeys）：
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
import { LoadingOutlined, CloseOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
import type { Editor } from '@tiptap/core'
import WordEditor from './WordEditor.vue'
import PaginatedPreview from '@/components/PaginatedPreview.vue'
import WordEditorHeader from './WordEditorHeader.vue'
import WordEditorToolbar from './WordEditorToolbar.vue'
import WordEditorStatusBar from './WordEditorStatusBar.vue'
import WordEditorOutline from './WordEditorOutline.vue'
import ChapterNavigator from './ChapterNavigator.vue'
import WordEditorSearchPanel from './WordEditorSearchPanel.vue'
import WordEditorTableToolbar from './WordEditorTableToolbar.vue'
import WordEditorImageToolbar from './WordEditorImageToolbar.vue'
import WordEditorContextMenu from './WordEditorContextMenu.vue'
import WordEditorRuler from './WordEditorRuler.vue'
import WordEditorProperties from './WordEditorProperties.vue'
import WordEditorComments from './WordEditorComments.vue'
import WordEditorVersionHistory from './WordEditorVersionHistory.vue'
import { exportToWord, printDocument } from './utils/word-export'
import { insertToc, updateToc } from './utils/toc-generator'
import type { AssignmentItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'
import { useTaskWorkflow } from '@/composables/useTaskWorkflow'
import { useEditorHotkeys } from '@/composables/useEditorHotkeys'
import { useImageUpload } from '@/composables/useImageUpload'
import { useFormatBrush } from '@/composables/useFormatBrush'
import { useAiAssistant } from '@/composables/useAiAssistant'
import { useChapterPersistence } from '@/composables/useChapterPersistence'
import { useEditorPanels } from '@/composables/useEditorPanels'
import { useEditorAiAssist } from '@/composables/useEditorAiAssist'
import { useEditorTextUtils } from '@/composables/useEditorTextUtils'
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

/* ---------------- 视图模式：连页编辑 / 分页预览 ---------------- */
/** true = 分页预览（只读，按 A4 逐页切分展示当前内容）；false = 连页编辑 */
const previewMode = ref(false)
/** 进入分页预览时从编辑器快照的 HTML */
const previewHtml = ref('')
watch(previewMode, (on) => {
  if (on) {
    previewHtml.value = editorInstance.value?.getHTML() ?? initialHtml.value ?? ''
  }
})

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

/* ---------------- 任务状态机（useTaskWorkflow） ---------------- */
const routeReadonly = computed(() => route.query.readonly === '1')
const projectOwnerId = ref('')
const currentTask = ref<AssignmentItem | null>(null)
const isMember = ref(false)

// 本地计算 canEdit（用于传递给 useChapterPersistence）
// 2026-09-03 产品确认最终口径：仅「本人分工」且未锁定的章节可编辑
// （assignee = 当前用户；已提审 submitted / 已通过 approved 内容锁定，不可编辑）
const canEdit = computed(() => {
  if (!currentTask.value) return false
  if (currentTask.value.assignee_id !== currentUserId.value) return false
  return !['submitted', 'approved'].includes(currentTask.value.status)
})

// 立即初始化 taskWorkflow（传入 loadChapter，虽然 loadChapter 还未定义，但 useTaskWorkflow 不会立即调用它）
let taskWorkflow: ReturnType<typeof useTaskWorkflow>
let _loadChapterForTask: (() => Promise<void>) | null = null

// 在 useChapterPersistence 后设置 loadChapter 回调
const setLoadChapter = (fn: () => Promise<void>) => {
  _loadChapterForTask = fn
  taskWorkflow = useTaskWorkflow({
    projectId,
    currentTask,
    projectOwnerId,
    isMember,
    loadChapter: fn,
  })
}

/* ---------------- 加载 / 保存（useChapterPersistence） ---------------- */
const {
  loading,
  initialContent,
  initialHtml,
  chapterTitle,
  saveStatus,
  saveHint,
  handleContentUpdate,
  saveNow,
  loadChapter,
  handleBeforeUnload,
  dispose: disposePersistence,
} = useChapterPersistence({
  projectId,
  chapterNo,
  getEditorHtml: () => editorRef.value?.getHTML() ?? '',
  getEditorJson: () => editorRef.value?.getJSON() ?? {},
  isReadOnly: () => !canEdit.value || routeReadonly.value,
  onLoaded: ({ projectOwnerId: ownerId, currentTask: task, isProjectMember }) => {
    projectOwnerId.value = ownerId
    currentTask.value = task
    isMember.value = isProjectMember
    // 确保 taskWorkflow 已初始化
    if (!taskWorkflow && _loadChapterForTask) {
      taskWorkflow = useTaskWorkflow({
        projectId,
        currentTask,
        projectOwnerId,
        isMember,
        loadChapter: _loadChapterForTask,
      })
    }
  },
})

// 设置 loadChapter 回调（在 useChapterPersistence 之后）
setLoadChapter(loadChapter)

/* ---------------- 从 taskWorkflow 解构状态和方法 ---------------- */
// 注意：需要确保 taskWorkflow 已初始化（在 setLoadChapter 后访问）
const taskState = computed(() => taskWorkflow || null)

const isAssignee = computed(() => taskState.value?.isAssignee.value ?? false)
const isReadOnly = computed(() => taskState.value?.isReadOnly.value ?? true)
const permissionHint = computed(() => taskState.value?.permissionHint.value ?? { type: 'info', text: '' })
const taskStatusText = computed(() => taskState.value?.taskStatusText.value ?? '')
const taskStatusColor = computed(() => taskState.value?.taskStatusColor.value ?? 'default')
const canAccept = computed(() => taskState.value?.canAccept.value ?? false)
const canSubmit = computed(() => taskState.value?.canSubmit.value ?? false)
const accepting = computed(() => taskState.value?.accepting.value ?? false)
const submittingTask = computed(() => taskState.value?.submittingTask.value ?? false)
const handleAccept = async () => taskState.value?.handleAccept()
const handleSubmit = async () => {
  await saveNow()
  await taskState.value?.handleSubmit()
}

/* ---------------- AI 辅助（useEditorAiAssist） ---------------- */
const {
  assistPrompt,
  assistMode,
  assisting,
  handleAssist,
} = useEditorAiAssist({
  projectId,
  chapterNo,
  getEditor: () => editorInstance.value,
  getCurrentTask: () => currentTask.value,
  getIsAssignee: () => isAssignee.value,
})

/** 导出为 Word .doc 文件 */
const handleExportWord = () => {
  const html = editorRef.value?.getHTML() ?? ''
  if (!html || html === '<p></p>') {
    message.warning('文档内容为空，无法导出')
    return
  }
  const filename = `${chapterTitle.value || chapterNo}_技术方案`
  exportToWord(html, filename, chapterTitle.value || '技术方案', undefined, {
    header: chapterTitle.value || '技术方案',
    showPageNumber: true,
    pageNumberAlign: 'center',
  })
  message.success('已导出 Word 文件')
}

/** 打印当前文档 */
const handlePrint = () => {
  const html = editorRef.value?.getHTML() ?? ''
  if (!html || html === '<p></p>') {
    message.warning('文档内容为空，无法打印')
    return
  }
  printDocument(html, chapterTitle.value || '技术方案', {
    header: chapterTitle.value || '技术方案',
    showPageNumber: true,
    pageNumberAlign: 'center',
  })
}

/** 标尺拖拽调整首行缩进 */
const handleRulerIndentChange = (valueEm: number) => {
  const ed = editorInstance.value
  if (!ed) return
  ed.chain().focus().setIndent(valueEm).run()
}

/** 插入目录 */
const handleInsertToc = () => {
  const ed = editorInstance.value
  if (!ed) return
  insertToc(ed, { title: '目录', levels: [1, 2, 3] })
  message.success('已插入目录')
}

/** 更新目录 */
const handleUpdateToc = () => {
  const ed = editorInstance.value
  if (!ed) return
  const updated = updateToc(ed, { title: '目录', levels: [1, 2, 3] })
  if (updated) {
    message.success('目录已更新')
  } else {
    message.info('未找到目录，请先插入目录')
  }
}

/** 恢复到指定版本 */
const handleRestoreVersion = (content: string) => {
  const ed = editorInstance.value
  if (!ed) return
  ed.chain().focus().setContent(content).run()
  message.success('已恢复到指定版本')
}

/** AI 操作处理 */
const handleAiAction = async (action: 'polish' | 'expand' | 'condense' | 'translate') => {
  const selectedText = aiAssistant.getSelectedText()
  if (!selectedText) {
    message.warning('请先选中需要处理的文字')
    return
  }
  const result = await applyAiAction(action)
  if (result) {
    message.success('AI 处理完成')
  } else {
    message.error('AI 处理失败，请稍后重试')
  }
}

/** 右键菜单 AI 动作（润色/翻译/续写）→ 复用选区处理链路 */
const handleContextAi = async (action: 'polish' | 'translate' | 'expand') => {
  await handleAiAction(action)
}

/** AI 自动排版 */
const handleAutoFormat = () => {
  const success = autoFormat()
  if (success) {
    message.success('已完成自动排版')
  } else {
    message.error('自动排版失败')
  }
}

/* ---------------- 面板显隐 / 缩放 / 弹窗状态（useEditorPanels） ---------------- */
const {
  outlineVisible,
  rulerVisible,
  propertiesVisible,
  commentsVisible,
  versionHistoryVisible,
  searchVisible,
  searchMode,
  zoom,
  linkModalOpen,
  linkUrl,
  fileInputRef,
  searchQuery,
  toggleProperties,
  toggleComments,
  toggleVersionHistory,
} = useEditorPanels()

/* ---------------- 左侧目录/大纲面板 ---------------- */
const leftPanelVisible = ref(true)
const leftPanelTab = ref<'navigator' | 'outline'>('navigator')

/** 章节导航跳转（由 ChapterNavigator 触发） */
const handleChapterNavigate = (_chapterNo: string) => {
  // 路由跳转由 ChapterNavigator 内部处理，仅保留状态同步入口
}

/* ---------------- 图片上传 composable ---------------- */
const { uploadImage, uploadProgress, uploading } = useImageUpload(
  ref<string | undefined>(projectId),
)

/* ---------------- 格式刷 composable（单一实例，provide 给 Toolbar） ---------------- */
const formatBrush = useFormatBrush(editorForComposables)
provide('formatBrush', formatBrush)

/* ---------------- AI 辅助 composable ---------------- */
const aiAssistant = useAiAssistant(
  () => editorInstance.value,
  projectId,
  chapterNo,
  () => currentTask.value?.id,
)
const { loading: aiLoading, applyAiAction, autoFormat } = aiAssistant

/* ---------------- 字号增减（useEditorTextUtils） ---------------- */
const { increaseFontSize, decreaseFontSize } = useEditorTextUtils(
  () => editorInstance.value,
)

/* ---------------- 快捷键系统（useEditorHotkeys） ---------------- */
useEditorHotkeys({
  getEditor: () => editorInstance.value,
  saveNow,
  getSearch: () => ({ mode: searchMode, visible: searchVisible }),
  increaseFontSize,
  decreaseFontSize,
  getFormatBrush: () => formatBrush,
})

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

/* ---------------- 返回 / 生命周期 ---------------- */
const handleBack = () => {
  void router.push({ name: 'Division', params: { projectId } })
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  void loadChapter()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  disposePersistence()
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

/* 左侧面板容器 */
.word-page__left-panel {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated, #1f1f1f);
  border-right: 1px solid var(--border-color, #303030);
}

.word-page__left-tabs {
  display: flex;
  align-items: center;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-color, #303030);
  flex-shrink: 0;
  height: 40px;
}

.word-page__left-tab {
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text-secondary, #999);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  margin-bottom: -1px;
}

.word-page__left-tab:hover {
  color: var(--text-primary, #fff);
}

.word-page__left-tab--active {
  color: var(--primary-color, #1890ff);
  border-bottom-color: var(--primary-color, #1890ff);
  font-weight: 500;
}

.word-page__left-close {
  margin-left: auto;
  color: var(--text-secondary, #999);
}

.word-page__left-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左侧面板关闭时的展开按钮 */
.word-page__left-expand {
  width: 24px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated, #1f1f1f);
  border-right: 1px solid var(--border-color, #303030);
  cursor: pointer;
  color: var(--text-secondary, #999);
  transition: color 0.15s;
}

.word-page__left-expand:hover {
  color: var(--primary-color, #1890ff);
}

/* 编辑区容器 */
.word-page__editor-area {
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  flex-direction: column;
}

/* 权限状态提示横幅 */
.word-page__permission-hint {
  margin: 8px 16px 0;
  flex-shrink: 0;
}
.word-page__permission-hint :deep(.ant-alert-message) {
  font-size: 13px;
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

/* 分页预览：撑满编辑区（内含自身滚动容器） */
.word-page__preview {
  flex: 1;
  min-height: 0;
}

/* AI 辅助编写区 */
.word-page__assist {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--bg-surface);
  border-top: 1px solid var(--border-color);
}
.word-page__assist .ant-input-affix-wrapper,
.word-page__assist .ant-input-group-wrapper {
  flex: 1;
}
.word-page__assist .ant-radio-group {
  flex: 0 0 auto;
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
