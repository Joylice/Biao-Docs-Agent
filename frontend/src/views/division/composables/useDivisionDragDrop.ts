import type { Ref } from 'vue'
import type { AssignmentItem, TaskStatus } from '@/types'
import type { UseUndoRedoReturn } from '@/composables/useUndoRedo'
import type { DivisionApi, DivisionNotify, DivisionRouteTarget, MoveAction } from './useDivisionBoard'
import { currentUserId } from '@/stores/currentUser'
import { useHotkeys } from '@/composables/useHotkeys'

/**
 * 看板拖拽交互（N9 拆分：从 useDivisionBoard 抽出）
 * 负责：状态转换动作解析、拖拽移动、撤销/重做（仅恢复本地视图）、快捷键
 */
export function useDivisionDragDrop(deps: {
  api: DivisionApi
  notify: DivisionNotify
  items: Ref<AssignmentItem[]>
  kanbanHistory: UseUndoRedoReturn<AssignmentItem[]>
  fetchAssignments: () => Promise<void>
  routerPush: (to: DivisionRouteTarget) => void
  projectId: string
}) {
  const { api, notify, items, kanbanHistory, fetchAssignments, routerPush, projectId } = deps

  const resolveMoveAction = (item: AssignmentItem, targetStatus: TaskStatus): MoveAction | null => {
    if (targetStatus === 'in_progress' && item.status === 'pending') {
      return { kind: 'accept', successText: `已领取：${item.title}` }
    }
    if (targetStatus === 'submitted' && ['in_progress', 'rejected'].includes(item.status)) {
      return { kind: 'submit', successText: `已提交：${item.title}` }
    }
    if (targetStatus === 'approved' && item.status === 'submitted') {
      return { kind: 'approve', successText: `已通过：${item.title}` }
    }
    if (targetStatus === 'rejected' && item.status === 'submitted') {
      return { kind: 'reject', successText: `已打回：${item.title}` }
    }
    return null
  }

  const handleMoveTask = async (item: AssignmentItem, targetStatus: TaskStatus) => {
    const action = resolveMoveAction(item, targetStatus)
    if (!action) {
      notify.warning('该状态转换不支持，请通过卡片按钮操作')
      return
    }
    kanbanHistory.push(items.value)
    try {
      if (action.kind === 'accept') {
        await api.acceptAssignment(projectId, item.id)
      } else if (action.kind === 'submit') {
        await api.submitAssignment(projectId, item.id)
      } else if (action.kind === 'approve') {
        await api.approveAssignment(projectId, item.id)
      } else {
        await api.rejectAssignment(projectId, item.id, '看板拖拽打回，请在编辑抽屉中查看详情')
      }
      notify.success(action.successText)
      await fetchAssignments()
    } catch (err) {
      const m = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
      notify.error(m || '状态变更失败')
      await fetchAssignments()
      kanbanHistory.reset(items.value)
    }
  }

  const handleSelectTask = (item: AssignmentItem) => {
    const isMyTask = item.assignee_id === currentUserId.value
    const contentLocked = item.status === 'submitted' || item.status === 'approved'
    routerPush({
      name: 'ChapterEditor',
      params: { projectId, chapterNo: item.chapter_no },
      query: isMyTask && !contentLocked ? undefined : { readonly: '1' },
    })
  }

  const handleKanbanUndo = () => {
    if (!kanbanHistory.undo()) {
      notify.info('没有可撤销的看板操作')
      return
    }
    notify.success('已撤销上一步移动（仅恢复本地视图，刷新后以后端数据为准）')
  }

  const handleKanbanRedo = () => {
    if (!kanbanHistory.redo()) {
      notify.info('没有可重做的看板操作')
      return
    }
    notify.success('已重做看板移动（仅恢复本地视图，刷新后以后端数据为准）')
  }

  useHotkeys([
    { combo: 'ctrl+z', handler: handleKanbanUndo },
    { combo: 'ctrl+shift+z', handler: handleKanbanRedo },
    { combo: 'ctrl+y', handler: handleKanbanRedo },
  ])

  return {
    resolveMoveAction,
    handleMoveTask,
    handleSelectTask,
    handleKanbanUndo,
    handleKanbanRedo,
  }
}
