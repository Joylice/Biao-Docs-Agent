/**
 * useAssistSelection：选区 AI 辅助（润色/扩写/缩写/翻译）.
 *
 * 职责：选中文字 AI 操作，走 assist-selection 端点（项目成员可用，
 * 不依赖分工记录），结果替换选区。
 *
 * 拆自 useAiAssistant（Phase 5 composable 职责拆分）.
 */
import { ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { assistSelection } from '@/api'

/** AI 操作类型 */
export type AiActionType =
  | 'polish'
  | 'expand'
  | 'condense'
  | 'translate'
  | 'correct'
  | 'formal'
  | 'simplify'

/** AI 操作配置 */
const AI_ACTION_CONFIG: Record<AiActionType, { label: string; prompt: string }> = {
  polish: {
    label: 'AI 润色',
    prompt: '请润色以下文字，优化语言表达，保持原意，使文字更加流畅、专业：',
  },
  expand: {
    label: 'AI 扩写',
    prompt: '请扩写以下内容，增加细节和说明，使内容更加丰富完整：',
  },
  condense: {
    label: 'AI 缩写',
    prompt: '请精简以下内容，保留核心信息，使文字更加简洁：',
  },
  translate: {
    label: 'AI 翻译',
    prompt: '请将以下内容翻译成英文（如果是英文则翻译成中文）：',
  },
  correct: {
    label: 'AI 纠错',
    prompt: '请检查并修正以下文字中的语法、拼写和标点错误：',
  },
  formal: {
    label: '正式化',
    prompt: '请将以下内容改写为正式、专业的商务/技术文档风格：',
  },
  simplify: {
    label: '简化',
    prompt: '请将以下内容简化，使用更通俗易懂的语言表达：',
  },
}

export interface UseAssistSelectionOptions {
  editor: () => Editor | undefined
  projectId: string
  chapterNo: string
}

export interface UseAssistSelectionReturn {
  loading: import('vue').Ref<boolean>
  currentAction: import('vue').Ref<AiActionType | null>
  applyAiAction: (action: AiActionType, replace?: boolean) => Promise<string | null>
  getSelectedText: () => string
  getAvailableActions: () => Array<{ type: AiActionType; label: string }>
}

export function useAssistSelection(options: UseAssistSelectionOptions): UseAssistSelectionReturn {
  const { editor, projectId, chapterNo } = options

  const loading = ref(false)
  const currentAction = ref<AiActionType | null>(null)

  const getSelectedText = (): string => {
    const ed = editor()
    if (!ed) return ''
    const { from, to } = ed.state.selection
    if (from === to) return ''
    return ed.state.doc.textBetween(from, to, ' ')
  }

  const applyAiAction = async (
    action: AiActionType,
    replace: boolean = true,
  ): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    const selectedText = getSelectedText()
    if (!selectedText) return null

    const backendAction: 'polish' | 'expand' | 'condense' | 'translate' =
      action === 'expand' || action === 'condense' || action === 'translate'
        ? action
        : 'polish'

    loading.value = true
    currentAction.value = action

    try {
      const { data } = await assistSelection(projectId, chapterNo, {
        text: selectedText,
        action: backendAction,
      })
      const result = data.data?.content ?? ''

      if (result && replace && result !== selectedText) {
        const { from, to } = ed.state.selection
        ed.chain().focus().deleteRange({ from, to }).insertContent(result).run()
      }

      return result
    } catch {
      return null
    } finally {
      loading.value = false
      currentAction.value = null
    }
  }

  const getAvailableActions = (): Array<{ type: AiActionType; label: string }> => {
    return Object.entries(AI_ACTION_CONFIG).map(([type, config]) => ({
      type: type as AiActionType,
      label: config.label,
    }))
  }

  return {
    loading,
    currentAction,
    applyAiAction,
    getSelectedText,
    getAvailableActions,
  }
}
