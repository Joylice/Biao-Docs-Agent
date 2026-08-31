/**
 * useChapterLoader：章节内容加载逻辑.
 *
 * 职责：并行 fetch content + assignments + project + members，
 * content_html 优先，否则 markdownToHtml(content)；
 * 标题从分工树查找；owner/任务数据经 onLoaded 回调。
 *
 * 拆自 useChapterPersistence（Phase 5 composable 职责拆分）.
 */
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { markdownToHtml } from '@/utils/markdown-converter'
import {
  fetchChapterContent,
  fetchChapterAssignments,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import type { AssignmentNode, AssignmentItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'

/** 加载完成回调数据（供页面装配任务状态等） */
export interface ChapterLoadData {
  chapterTitle: string
  projectOwnerId: string
  currentTask: AssignmentItem | null
  assignments: AssignmentNode[]
  isProjectMember: boolean
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

export interface UseChapterLoaderOptions {
  projectId: string
  chapterNo: string
  onLoaded?: (data: ChapterLoadData) => void
}

export interface UseChapterLoaderReturn {
  loading: import('vue').Ref<boolean>
  initialHtml: import('vue').Ref<string>
  chapterTitle: import('vue').Ref<string>
  /** 设置后用于保存基线对比（由编排层读取） */
  lastSavedHtml: import('vue').Ref<string>
  loadChapter: () => Promise<void>
}

export function useChapterLoader(options: UseChapterLoaderOptions): UseChapterLoaderReturn {
  const { projectId, chapterNo, onLoaded } = options

  const loading = ref(false)
  const initialHtml = ref('')
  const chapterTitle = ref('')
  const lastSavedHtml = ref('')

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

  return {
    loading,
    initialHtml,
    chapterTitle,
    lastSavedHtml,
    loadChapter,
  }
}
