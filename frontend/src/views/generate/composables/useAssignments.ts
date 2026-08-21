import { ref } from 'vue'
import { fetchChapterAssignments } from '@/api'
import type { AssignmentNode } from '@/types'

/**
 * 章节分工映射：拉取分工树并扁平化为 chapter_no → 节点 的 Map。
 * WS task_* 事件与页面初始化均调用 fetchAssignments 刷新。
 */
export function useAssignments(projectId: string) {
  const assignmentMap = ref<Map<string, AssignmentNode>>(new Map())

  const collectAssignments = (items: AssignmentNode[], map: Map<string, AssignmentNode>) => {
    for (const item of items) {
      if (item.chapter_no) map.set(item.chapter_no, item)
      if (item.children?.length) collectAssignments(item.children, map)
    }
  }

  const fetchAssignments = async () => {
    try {
      const { data } = await fetchChapterAssignments(projectId)
      if (data.code === 0) {
        const map = new Map<string, AssignmentNode>()
        collectAssignments(data.data?.items ?? [], map)
        assignmentMap.value = map
      }
    } catch { /* 静默 */ }
  }

  return { assignmentMap, fetchAssignments }
}
