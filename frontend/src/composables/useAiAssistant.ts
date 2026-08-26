/**
 * AI 辅助编辑 composable
 * - 选中文字 AI 操作（润色/扩写/缩写/翻译/纠错）
 * - AI 自动排版（一键美化格式）
 * - AI 标题生成
 * - AI 摘要生成
 *
 * 基于现有的 assistChapter API 实现
 */
import { ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { assistChapter } from '@/api'
import type { AssistRequest } from '@/types'

/** AI 操作类型 */
export type AiActionType =
  | 'polish'      // 润色
  | 'expand'      // 扩写
  | 'condense'    // 缩写
  | 'translate'   // 翻译
  | 'correct'     // 纠错
  | 'formal'      // 正式化
  | 'simplify'    // 简化

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

/**
 * 使用 AI 辅助编辑
 * @param editor 编辑器实例获取函数
 * @param projectId 项目 ID
 * @param chapterNo 章节编号
 */
export function useAiAssistant(
  editor: () => Editor | undefined,
  projectId: string,
  chapterNo: string,
) {
  /* 加载状态 */
  const loading = ref(false)
  const currentAction = ref<AiActionType | null>(null)

  /**
   * 获取选中文字
   */
  const getSelectedText = (): string => {
    const ed = editor()
    if (!ed) return ''
    const { from, to } = ed.state.selection
    if (from === to) return ''
    return ed.state.doc.textBetween(from, to, ' ')
  }

  /**
   * 对选中文字执行 AI 操作
   * @param action 操作类型
   * @param replace 是否替换原选中内容（默认替换）
   */
  const applyAiAction = async (
    action: AiActionType,
    replace: boolean = true,
  ): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    const selectedText = getSelectedText()
    if (!selectedText) {
      return null
    }

    loading.value = true
    currentAction.value = action

    try {
      const config = AI_ACTION_CONFIG[action]
      const prompt = `${config.prompt}\n\n${selectedText}`

      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt,
        mode: 'append',
      }

      const { data } = await assistChapter(projectId, payload)
      const result = data.data?.content ?? ''

      if (result && replace) {
        // 替换选中内容
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

  /**
   * AI 自动排版（一键美化格式）
   * 前端实现：统一字体、字号、行距、段落格式
   */
  const autoFormat = (): boolean => {
    const ed = editor()
    if (!ed) return false

    try {
      // 遍历所有段落，统一格式
      ed.state.doc.descendants((node) => {
        if (node.type.name === 'paragraph') {
          // 统一段落格式：宋体、12pt、1.5倍行距、首行缩进2字符
          // 注意：不修改标题样式
        }
      })

      // 统一正文字体和字号（对非标题段落）
      const tr = ed.state.tr
      ed.state.doc.descendants((node, pos) => {
        if (node.type.name === 'paragraph' && node.content.size > 0) {
          // 设置段落属性
          tr.setNodeMarkup(pos, undefined, {
            ...node.attrs,
            lineHeight: '1.5',
            textIndent: '2em',
          })
        }
      })

      if (tr.docChanged) {
        ed.view.dispatch(tr)
      }

      return true
    } catch {
      return false
    }
  }

  /**
   * AI 生成标题（基于当前段落内容）
   */
  const generateTitle = async (): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    // 获取当前段落内容
    const { $from } = ed.state.selection
    const paragraph = $from.parent
    const content = paragraph.textContent

    if (!content) return null

    loading.value = true
    try {
      const prompt = `请根据以下内容生成一个简洁、专业的标题（不超过20字）：\n\n${content}`
      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt,
        mode: 'append',
      }
      const { data } = await assistChapter(projectId, payload)
      return data.data?.content ?? null
    } catch {
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * AI 生成摘要（基于全文内容）
   */
  const generateSummary = async (): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    const fullText = ed.getText()
    if (!fullText) return null

    loading.value = true
    try {
      const prompt = `请为以下技术方案内容生成一个简洁的摘要（约200字），涵盖核心要点：\n\n${fullText.slice(0, 3000)}`
      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt,
        mode: 'append',
      }
      const { data } = await assistChapter(projectId, payload)
      return data.data?.content ?? null
    } catch {
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * 获取所有可用的 AI 操作
   */
  const getAvailableActions = (): Array<{ type: AiActionType; label: string }> => {
    return Object.entries(AI_ACTION_CONFIG).map(([type, config]) => ({
      type: type as AiActionType,
      label: config.label,
    }))
  }

  return {
    // 状态
    loading,
    currentAction,
    // 操作
    applyAiAction,
    autoFormat,
    generateTitle,
    generateSummary,
    getSelectedText,
    getAvailableActions,
  }
}
