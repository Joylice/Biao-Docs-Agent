/**
 * useEditorAiAssist：章节级 AI 辅助 composable
 *
 * 从 WordEditorPage 抽离：
 * - assistPrompt / assistMode / assisting 状态
 * - handleAssist 方法（调用 assistChapter API，插入/覆盖内容）
 */
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import type { Editor } from '@tiptap/core'
import { assistChapter } from '@/api'
import type { AssignmentItem, AssistRequest } from '@/types'
import { markdownToHtml } from '@/utils/markdown-converter'

export function useEditorAiAssist(options: {
  projectId: string
  chapterNo: string
  getEditor: () => Editor | undefined
  getCurrentTask: () => AssignmentItem | null
  getIsAssignee: () => boolean
}) {
  const { projectId, chapterNo, getEditor, getCurrentTask, getIsAssignee } = options

  const assistPrompt = ref('')
  const assistMode = ref<'append' | 'overwrite'>('append')
  const assisting = ref(false)

  const handleAssist = async () => {
    if (!assistPrompt.value.trim()) return
    const currentTask = getCurrentTask()
    if (!currentTask) {
      message.error('未找到当前章节的分工记录，请先在分工页推送分工')
      return
    }
    if (!getIsAssignee()) {
      message.error('仅章节负责人可使用 AI 辅助功能')
      return
    }
    if (!['in_progress', 'rejected'].includes(currentTask.status)) {
      message.error('请先领取任务后再使用 AI 辅助')
      return
    }

    assisting.value = true
    try {
      const payload: AssistRequest = {
        chapter_no: chapterNo,
        prompt: assistPrompt.value,
        mode: assistMode.value,
      }
      console.log('[AI辅助] 请求参数:', { assignmentId: currentTask.id, payload })
      const { data } = await assistChapter(projectId, currentTask.id, payload)
      console.log('[AI辅助] 响应:', data)
      const newContent = data.data?.content
      if (typeof newContent === 'string' && newContent.trim()) {
        const html = markdownToHtml(newContent)
        const inst = getEditor()
        if (inst) {
          if (assistMode.value === 'append') {
            inst.chain().focus().insertContent(html).run()
          } else {
            inst.chain().focus().setContent(html).run()
          }
        }
        message.success('AI 辅助完成，内容已插入')
        assistPrompt.value = ''
      } else {
        message.warning('AI 未生成有效内容，请调整提示词后重试')
      }
    } catch (err) {
      console.error('[AI辅助] 失败:', err)
      const e = err as {
        response?: { status?: number; data?: { message?: string } }
        message?: string
      }
      const status = e?.response?.status
      const body = e?.response?.data
      const msg = body?.message || e?.message
      let friendlyMsg = 'AI 辅助失败'
      if (status === 400) {
        friendlyMsg = `请求参数错误：${msg || '请检查输入'}`
      } else if (status === 403) {
        friendlyMsg = `权限不足：${msg || '仅章节负责人可使用'}`
      } else if (status === 5011) {
        friendlyMsg = `AI 服务异常：${msg || '请稍后重试或联系管理员'}`
      } else if (msg) {
        friendlyMsg = msg
      }
      message.error(friendlyMsg, 5)
    } finally {
      assisting.value = false
    }
  }

  return {
    assistPrompt,
    assistMode,
    assisting,
    handleAssist,
  }
}
