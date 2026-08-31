/**
 * useChapterPersistence：编排层 — 组合 useChapterLoader + useChapterSave.
 *
 * Phase 5 拆分后：加载逻辑 → useChapterLoader，保存状态机 → useChapterSave。
 * 本函数保持原接口不变，调用方（WordEditorPage）无需改动.
 *
 * 保留 re-export 公共类型和工具函数（向后兼容）.
 */
import {
  useChapterLoader,
  type UseChapterLoaderOptions,
} from '@/composables/useChapterLoader'
import { useChapterSave } from '@/composables/useChapterSave'
import type { ComputedRef, Ref } from 'vue'
import type { SaveStatus } from '@/types/editor'

// re-export 公共类型和工具函数（向后兼容）
export type { ChapterLoadData } from '@/composables/useChapterLoader'
export type { AssignmentNode, AssignmentItem } from '@/types'
export { findChapterTitle, flattenAssignments } from '@/composables/useChapterLoader'

export interface UseChapterPersistenceOptions extends UseChapterLoaderOptions {
  /** 读取编辑器当前 HTML（由页面传入） */
  getEditorHtml: () => string
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
  dispose: () => void
}

export function useChapterPersistence(
  options: UseChapterPersistenceOptions,
): UseChapterPersistenceReturn {
  const { projectId, chapterNo, getEditorHtml, onLoaded, isReadOnly } = options

  const loader = useChapterLoader({ projectId, chapterNo, onLoaded })

  const saver = useChapterSave({
    projectId,
    chapterNo,
    getEditorHtml,
    lastSavedHtml: loader.lastSavedHtml,
    isReadOnly,
  })

  return {
    loading: loader.loading,
    initialHtml: loader.initialHtml,
    chapterTitle: loader.chapterTitle,
    saveStatus: saver.saveStatus,
    dirty: saver.dirty,
    saveHint: saver.saveHint,
    handleContentUpdate: saver.handleContentUpdate,
    saveNow: saver.saveNow,
    loadChapter: loader.loadChapter,
    handleBeforeUnload: saver.handleBeforeUnload,
    dispose: saver.dispose,
  }
}
