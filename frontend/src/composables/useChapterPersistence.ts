/**
 * useChapterPersistence：章节内容加载 / 保存 / 自动保存持久化逻辑.
 *
 * 职责：
 * - 加载：并行 fetch content + assignments + project；content_html 优先，
 *   否则 markdownToHtml(content)；标题从分工树查找；owner/任务数据经 onLoaded 回调
 * - 保存：htmlToMarkdown(getHTML()) 得 markdown，连同 HTML 双字段 PUT 保存
 * - 自动保存：内容变化 2s 防抖；失败自动重试 2 次；Ctrl+S 手动保存
 * - beforeunload 拦截未保存离开
 *
 * 页面组装：WordEditorPage 负责编辑器实例（getEditorHtml）与模板绑定，
 * 本 composable 只关心数据流与状态机，不触碰 DOM。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { markdownToHtml, htmlToMarkdown } from '@/components/editor/utils/markdown-converter'
import {
  fetchChapterContent,
  saveChapterContent,
  fetchChapterAssignments,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import type { AssignmentNode, AssignmentItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'
import type { SaveStatus } from '@/components/editor/WordEditorStatusBar.vue'

/** 加载完成回调数据（供页面装配任务状态等） */
export interface ChapterLoadData {
  /** 章节标题（分工树中查找） */
  chapterTitle: string
  /** 项目 owner id */
  projectOwnerId: string
  /** 当前章节任务（分工树中匹配 chapter_no） */
  currentTask: AssignmentItem | null
  /** 分工树原始节点（页面可能还需要） */
  assignments: AssignmentNode[]
  /** 当前用户是否为项目成员（决定编辑权限） */
  isProjectMember: boolean
}

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

export interface UseChapterPersistenceOptions {
  projectId: string
  chapterNo: string
  /** 读取编辑器当前 HTML（由页面传入） */
  getEditorHtml: () => string
  /** 加载完成回调：装配标题/owner/当前任务 */
  onLoaded?: (data: ChapterLoadData) => void
  /** 只读模式标志（只读时跳过自动保存和 beforeunload 拦截） */
  isReadOnly?: () => boolean
}

export interface UseChapterPersistenceReturn {
  loading: Ref<boolean>
  initialHtml: Ref<string>
  chapterTitle: Ref<string>
  saveStatus: Ref<SaveStatus>
  dirty: Ref<boolean>
  saveHint: ComputedRef<string>
  handleContentUpdate: (html: string) => void
  saveNow: () => void
  loadChapter: () => Promise<void>
  handleBeforeUnload: (e: BeforeUnloadEvent) => void
  /** 卸载时清理定时器 */
  dispose: () => void
}

/** 在分工树中递归查找 chapter_no 对应的标题 */
export const findChapterTitle = (nodes: AssignmentNode[], target: string): string => {
  for (const node of nodes) {
    if (node.chapter_no === target) return node.title
    if (node.children?.length) {
      const found = findChapterTitle(node.children, target)
      if (found) return found
    }
  }
  return ''
}

/** 将分工树扁平化为任务列表 */
export const flattenAssignments = (nodes: AssignmentNode[]): AssignmentItem[] => {
  const flat: AssignmentItem[] = []
  const walk = (list: AssignmentNode[]) => {
    list.forEach((node) => {
      if (node.id) flat.push(node as unknown as AssignmentItem)
      if (node.children?.length) walk(node.children)
    })
  }
  walk(nodes)
  return flat
}

export function useChapterPersistence(
  options: UseChapterPersistenceOptions,
): UseChapterPersistenceReturn {
  const { projectId, chapterNo, getEditorHtml, onLoaded, isReadOnly } = options

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

  const saveHint = computed(() =>
    dirty.value && saveStatus.value === 'idle' ? '待自动保存' : SAVE_HINT[saveStatus.value],
  )

  /* ---------------- 内容变化 → 防抖自动保存 ---------------- */
  const handleContentUpdate = (html: string) => {
    // 只读模式下不触发自动保存
    if (isReadOnly?.()) return
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
    const html = getEditorHtml()
    if (!html || loading.value || saveStatus.value === 'saving') return
    if (!dirty.value && source === 'auto') return

    saveStatus.value = 'saving'
    try {
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

  /* ---------------- 数据加载 ---------------- */
  const loadChapter = async () => {
    loading.value = true
    try {
      const [contentRes, assignmentsRes, projectRes, membersRes] = await Promise.all([
        fetchChapterContent(projectId, chapterNo),
        fetchChapterAssignments(projectId),
        fetchProject(projectId),
        fetchProjectMembers(projectId),
      ])
      const data = contentRes.data.data
      // content_html 优先；缺失时将 markdown 转 HTML 供富文本编辑
      initialHtml.value = data?.content_html || (data?.content ? markdownToHtml(data.content) : '')
      lastSavedHtml.value = initialHtml.value

      const items = assignmentsRes.data.data?.items ?? []
      const title = findChapterTitle(items, chapterNo)
      chapterTitle.value = title

      const ownerId = projectRes.data.data?.owner_id || ''
      const memberIds = (membersRes.data.data?.items ?? []).map((m) => m.user_id)
      const isProjectMember = memberIds.includes(currentUserId.value)
      const currentTask = flattenAssignments(items).find((t) => t.chapter_no === chapterNo) || null
      onLoaded?.({
        chapterTitle: title,
        projectOwnerId: ownerId,
        currentTask,
        assignments: items,
        isProjectMember,
      })
    } catch {
      message.error('章节内容加载失败')
    } finally {
      loading.value = false
    }
  }

  /* ---------------- 页面关闭/刷新拦截 ---------------- */
  const handleBeforeUnload = (e: BeforeUnloadEvent) => {
    // 只读模式下不拦截
    if (isReadOnly?.()) return
    if (dirty.value) {
      e.preventDefault()
      e.returnValue = ''
    }
  }

  /** 卸载时清理定时器 */
  const dispose = () => {
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    if (retryTimer) clearTimeout(retryTimer)
  }

  return {
    loading,
    initialHtml,
    chapterTitle,
    saveStatus,
    dirty,
    saveHint,
    handleContentUpdate,
    saveNow,
    loadChapter,
    handleBeforeUnload,
    dispose,
  }
}
