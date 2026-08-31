/**
 * useAiAssistant：编排层 — 组合 useAssistSelection + useAssistChapter.
 *
 * Phase 5 拆分后：选区辅助 → useAssistSelection，整章辅助 → useAssistChapter。
 * 本函数保持原接口不变，调用方（WordEditorPage）无需改动.
 *
 * 保留 re-export 公共类型（向后兼容）.
 */
import { computed, type Ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { useAssistSelection, type AiActionType } from '@/composables/useAssistSelection'
import { useAssistChapter } from '@/composables/useAssistChapter'

// re-export 公共类型（向后兼容）
export type { AiActionType } from '@/composables/useAssistSelection'

export function useAiAssistant(
  editor: () => Editor | undefined,
  projectId: string,
  chapterNo: string,
  assignmentId?: string | (() => string | undefined),
) {
  const selection = useAssistSelection({ editor, projectId, chapterNo })
  const chapter = useAssistChapter({ editor, projectId, chapterNo, assignmentId })

  /** 共享 loading：选区或整章任一在执行中即为 loading */
  const loading = computed(() => selection.loading.value || chapter.loading.value) as Ref<boolean>

  /** 共享 currentAction：选区或整章任一在执行中的 action */
  const currentAction = computed(
    () => selection.currentAction.value || chapter.currentAction.value,
  ) as Ref<AiActionType | null>

  return {
    loading,
    currentAction,
    // 选区操作
    applyAiAction: selection.applyAiAction,
    getSelectedText: selection.getSelectedText,
    getAvailableActions: selection.getAvailableActions,
    // 整章操作
    autoFormat: chapter.autoFormat,
    generateTitle: chapter.generateTitle,
    generateSummary: chapter.generateSummary,
  }
}
