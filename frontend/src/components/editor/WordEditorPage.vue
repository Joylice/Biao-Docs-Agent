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
        <a-tag
          v-if="taskStatusText"
          :color="taskStatusColor"
        >
          {{ taskStatusText }}
        </a-tag>
        <a-tag
          v-if="isReadOnly"
          color="default"
        >
          只读模式
        </a-tag>
      </div>
      <div class="word-page__header-right">
        <!-- 任务状态操作按钮 -->
        <a-button
          v-if="canAccept"
          size="small"
          type="primary"
          :loading="accepting"
          @click="handleAccept"
        >
          领取任务
        </a-button>
        <a-button
          v-if="canSubmit"
          size="small"
          type="primary"
          :loading="submittingTask"
          @click="handleSubmit"
        >
          提交审核
        </a-button>
        <a-button
          v-if="canApprove"
          size="small"
          :loading="approving"
          @click="handleApprove"
        >
          审核通过
        </a-button>
        <a-button
          v-if="canReject"
          size="small"
          danger
          @click="showRejectModal = true"
        >
          打回
        </a-button>
        <a-divider
          v-if="canAccept || canSubmit || canApprove || canReject"
          type="vertical"
        />
        <span
          v-if="!isReadOnly"
          class="word-page__save-hint"
          :class="`word-page__save-hint--${saveStatus}`"
        >
          {{ saveHint }}
        </span>
        <a-button
          v-if="!isReadOnly"
          size="small"
          type="primary"
          :loading="saveStatus === 'saving'"
          aria-label="保存章节内容"
          @click="saveNow"
        >
          保存
        </a-button>
        <a-button
          size="small"
          aria-label="导出Word"
          @click="handleExportWord"
        >
          <template #icon>
            <DownloadOutlined />
          </template>
          导出
        </a-button>
        <a-button
          size="small"
          aria-label="打印"
          @click="handlePrint"
        >
          <template #icon>
            <PrinterOutlined />
          </template>
          打印
        </a-button>
        <a-dropdown>
          <a-button size="small" aria-label="目录">
            <template #icon>
              <UnorderedListOutlined />
            </template>
            目录
          </a-button>
          <template #overlay>
            <a-menu>
              <a-menu-item key="insert" @click="handleInsertToc">
                插入目录
              </a-menu-item>
              <a-menu-item key="update" @click="handleUpdateToc">
                更新目录
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <a-button
          size="small"
          :type="propertiesVisible ? 'primary' : 'default'"
          aria-label="属性面板"
          @click="toggleProperties"
        >
          <template #icon>
            <SettingOutlined />
          </template>
          属性
        </a-button>
        <a-button
          size="small"
          :type="commentsVisible ? 'primary' : 'default'"
          aria-label="批注面板"
          @click="toggleComments"
        >
          <template #icon>
            <CommentOutlined />
          </template>
          批注
        </a-button>
        <a-button
          size="small"
          :type="versionHistoryVisible ? 'primary' : 'default'"
          aria-label="版本历史"
          @click="toggleVersionHistory"
        >
          <template #icon>
            <HistoryOutlined />
          </template>
          版本
        </a-button>
        <a-dropdown>
          <a-button size="small" type="primary" :loading="aiLoading" aria-label="AI 辅助">
            <template #icon>
              <RobotOutlined />
            </template>
            AI 辅助
          </a-button>
          <template #overlay>
            <a-menu>
              <a-menu-item key="polish" @click="handleAiAction('polish')">
                <template #icon><EditOutlined /></template>
                AI 润色（选中文字）
              </a-menu-item>
              <a-menu-item key="expand" @click="handleAiAction('expand')">
                <template #icon><ExpandOutlined /></template>
                AI 扩写（选中文字）
              </a-menu-item>
              <a-menu-item key="condense" @click="handleAiAction('condense')">
                <template #icon><CompressOutlined /></template>
                AI 缩写（选中文字）
              </a-menu-item>
              <a-menu-item key="translate" @click="handleAiAction('translate')">
                <template #icon><TranslationOutlined /></template>
                AI 翻译（选中文字）
              </a-menu-item>
              <a-menu-divider />
              <a-menu-item key="autoFormat" @click="handleAutoFormat">
                <template #icon><BgColorsOutlined /></template>
                AI 自动排版
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>
    </header>

    <!-- Ribbon 工具栏（只读模式下隐藏） -->
    <WordEditorToolbar
      v-if="!isReadOnly"
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
        <!-- 水平标尺（视图选项卡控制显隐） -->
        <WordEditorRuler
          v-if="rulerVisible"
          class="word-page__ruler"
          :editor="editorInstance"
          @indent-change="handleRulerIndentChange"
        />
        <a-spin
          :spinning="loading"
          wrapper-class-name="word-page__editor-spin"
        >
          <WordEditor
            ref="editorRef"
            class="word-page__editor"
            :content="initialHtml"
            :readonly="loading || isReadOnly"
            :project-id="projectId"
            :style="{ '--paper-zoom': zoom / 100 }"
            placeholder="请输入章节内容，支持标题、列表、表格等富文本排版..."
            @update:content="handleContentUpdate"
          />
        </a-spin>

        <!-- AI 辅助编写（只读模式下隐藏；整章追加/覆盖仅 assignee，选区 AI 见顶部/右键菜单） -->
        <div v-if="!isReadOnly" class="word-page__assist">
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

      <!-- 右侧：批注面板 -->
      <WordEditorComments
        v-if="commentsVisible"
        class="word-page__comments"
        :editor="editorInstance"
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

    <!-- 打回原因弹窗 -->
    <a-modal
      v-model:open="showRejectModal"
      title="打回原因"
      ok-text="确认打回"
      cancel-text="取消"
      :confirm-loading="rejectingTask"
      @ok="handleReject"
    >
      <a-textarea
        v-model:value="rejectComment"
        :rows="4"
        placeholder="请输入打回原因..."
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
import { ArrowLeftOutlined, LoadingOutlined, DownloadOutlined, PrinterOutlined, UnorderedListOutlined, SettingOutlined, CommentOutlined, HistoryOutlined, RobotOutlined, EditOutlined, ExpandOutlined, CompressOutlined, TranslationOutlined, BgColorsOutlined, CloseOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
import type { Editor } from '@tiptap/core'
import WordEditor from './WordEditor.vue'
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
import { usePermission } from '@/composables/usePermission'
import { useTaskWorkflow } from '@/composables/useTaskWorkflow'
import { useHotkeys } from '@/composables/useHotkeys'
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
const { isProjectOwner } = usePermission()
const canEdit = computed(() => {
  if (!currentTask.value) return false
  if (isProjectOwner(projectOwnerId.value)) return false
  if (!isMember.value) return false
  return true
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
const canApprove = computed(() => taskState.value?.canApprove.value ?? false)
const canReject = computed(() => taskState.value?.canReject.value ?? false)
const accepting = computed(() => taskState.value?.accepting.value ?? false)
const submittingTask = computed(() => taskState.value?.submittingTask.value ?? false)
const approving = computed(() => taskState.value?.approving.value ?? false)
const rejectingTask = computed(() => taskState.value?.rejectingTask.value ?? false)
const showRejectModal = computed({
  get: () => taskState.value?.showRejectModal.value ?? false,
  set: (val) => { if (taskState.value) taskState.value.showRejectModal.value = val }
})
const rejectComment = computed({
  get: () => taskState.value?.rejectComment.value ?? '',
  set: (val) => { if (taskState.value) taskState.value.rejectComment.value = val }
})
const handleAccept = async () => taskState.value?.handleAccept()
const handleSubmit = async () => {
  await saveNow()
  await taskState.value?.handleSubmit()
}
const handleApprove = async () => taskState.value?.handleApprove()
const handleReject = async () => taskState.value?.handleReject()

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
