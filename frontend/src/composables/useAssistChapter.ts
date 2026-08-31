/**
 * useAssistChapter：整章 AI 辅助（标题生成/摘要生成/自动排版）.
 *
 * 职责：走 assist-generate 整章接口（需 assignmentId），
 * 含 AI 标题生成、摘要生成、自动排版（一键美化格式）。
 *
 * 拆自 useAiAssistant（Phase 5 composable 职责拆分）.
 */
import { ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { assistChapter } from '@/api'
import type { AssistRequest } from '@/types'
import type { AiActionType } from '@/composables/useAssistSelection'

export interface UseAssistChapterOptions {
  editor: () => Editor | undefined
  projectId: string
  chapterNo: string
  assignmentId?: string | (() => string | undefined)
}

export interface UseAssistChapterReturn {
  loading: import('vue').Ref<boolean>
  currentAction: import('vue').Ref<AiActionType | null>
  autoFormat: () => boolean
  generateTitle: () => Promise<string | null>
  generateSummary: () => Promise<string | null>
}

export function useAssistChapter(options: UseAssistChapterOptions): UseAssistChapterReturn {
  const { editor, projectId, chapterNo, assignmentId } = options

  const loading = ref(false)
  const currentAction = ref<AiActionType | null>(null)

  const autoFormat = (): boolean => {
    const ed = editor()
    if (!ed) return false

    try {
      const tr = ed.state.tr
      let changed = false
      ed.state.doc.descendants((node, pos) => {
        if (node.type.name === 'paragraph' && node.content.size > 0) {
          const attrs = { ...node.attrs }
          if (attrs.lineHeight !== '1.5') {
            attrs.lineHeight = '1.5'
            changed = true
          }
          if (attrs.textIndent !== '2em') {
            attrs.textIndent = '2em'
            changed = true
          }
          const mark = node.marks.find((m) => m.type.name === 'fontSize')
          if (!mark || (mark as { attrs?: { fontSize?: string } }).attrs?.fontSize !== '12pt') {
            if (node.marks.some((m) => m.type.name === 'fontSize')) {
              tr.removeMark(pos, pos + node.nodeSize, ed.schema.marks.fontSize)
            }
            tr.addMark(pos, pos + node.nodeSize, ed.schema.marks.fontSize.create({ fontSize: '12pt' }))
            changed = true
          }
        }
      })

      if (changed) {
        ed.view.dispatch(tr)
      }

      return true
    } catch {
      return false
    }
  }

  const generateTitle = async (): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    const { $from } = ed.state.selection
    const paragraph = $from.parent
    const content = paragraph.textContent

    if (!content) return null

    loading.value = true
    currentAction.value = 'polish'
    try {
      const prompt = `请根据以下内容生成一个简洁、专业的标题（不超过20字）：\n\n${content}`
      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt,
        mode: 'append',
      }
      const aid = typeof assignmentId === 'function' ? assignmentId() : assignmentId
      if (!aid) return null
      const { data } = await assistChapter(projectId, aid, payload)
      return data.data?.content ?? null
    } catch {
      return null
    } finally {
      loading.value = false
      currentAction.value = null
    }
  }

  const generateSummary = async (): Promise<string | null> => {
    const ed = editor()
    if (!ed) return null

    const fullText = ed.getText()
    if (!fullText) return null

    loading.value = true
    currentAction.value = 'condense'
    try {
      const prompt = `请为以下技术方案内容生成一个简洁的摘要（约200字），涵盖核心要点：\n\n${fullText.slice(0, 3000)}`
      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt,
        mode: 'append',
      }
      const aid = typeof assignmentId === 'function' ? assignmentId() : assignmentId
      if (!aid) return null
      const { data } = await assistChapter(projectId, aid, payload)
      return data.data?.content ?? null
    } catch {
      return null
    } finally {
      loading.value = false
      currentAction.value = null
    }
  }

  return {
    loading,
    currentAction,
    autoFormat,
    generateTitle,
    generateSummary,
  }
}
