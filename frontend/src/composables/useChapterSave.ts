/**
 * useChapterSave：章节保存 / 自动保存 / 重试状态机.
 *
 * 职责：内容变化防抖自动保存（2s）、失败重试 2 次、Ctrl+S 手动保存、
 * beforeunload 拦截未保存离开。
 *
 * 拆自 useChapterPersistence（Phase 5 composable 职责拆分）.
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { htmlToMarkdown } from '@/utils/markdown-converter'
import { saveChapterContent } from '@/api'
import type { SaveStatus } from '@/types/editor'

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

export interface UseChapterSaveOptions {
  projectId: string
  chapterNo: string
  /** 读取编辑器当前 HTML（由页面传入） */
  getEditorHtml: () => string
  /** 保存基线 HTML（由 loader 提供，初始值 = initialHtml） */
  lastSavedHtml: Ref<string>
  /** 只读模式标志（只读时跳过自动保存和 beforeunload 拦截） */
  isReadOnly?: () => boolean
}

export interface UseChapterSaveReturn {
  saveStatus: Ref<SaveStatus>
  dirty: Ref<boolean>
  saveHint: ComputedRef<string>
  handleContentUpdate: (html: string) => void
  saveNow: () => void
  handleBeforeUnload: (e: BeforeUnloadEvent) => void
  /** 卸载时清理定时器 */
  dispose: () => void
}

export function useChapterSave(options: UseChapterSaveOptions): UseChapterSaveReturn {
  const { projectId, chapterNo, getEditorHtml, lastSavedHtml, isReadOnly } = options

  const saveStatus = ref<SaveStatus>('idle')
  const dirty = ref(false)
  const retryCount = ref(0)

  let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  const saveHint = computed(() =>
    dirty.value && saveStatus.value === 'idle' ? '待自动保存' : SAVE_HINT[saveStatus.value],
  )

  const handleContentUpdate = (html: string) => {
    if (isReadOnly?.()) return
    dirty.value = html !== lastSavedHtml.value
    if (!dirty.value) {
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

  const doSave = async (source: 'auto' | 'manual') => {
    const html = getEditorHtml()
    if (!html || saveStatus.value === 'saving') return
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

  const saveNow = () => {
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer)
      autoSaveTimer = null
    }
    void doSave('manual')
  }

  const handleBeforeUnload = (e: BeforeUnloadEvent) => {
    if (isReadOnly?.()) return
    if (dirty.value) {
      e.preventDefault()
      e.returnValue = ''
    }
  }

  const dispose = () => {
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    if (retryTimer) clearTimeout(retryTimer)
  }

  return {
    saveStatus,
    dirty,
    saveHint,
    handleContentUpdate,
    saveNow,
    handleBeforeUnload,
    dispose,
  }
}
