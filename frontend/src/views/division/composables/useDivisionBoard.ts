import { ref, computed, onMounted } from 'vue'
import { usePermission } from '@/composables/usePermission'
import { useUndoRedo } from '@/composables/useUndoRedo'
import { currentUserId } from '@/stores/currentUser'
import type {
  AssignmentItem,
  TaskStatus,
  AssignmentNode,
  ProjectMember,
  OutlineItem,
} from '@/types'
import type { fetchWorkflowStatus, confirmDivision } from '@/api/workflow'
import type {
  fetchChapterAssignments,
  upsertChapterAssignments,
  acceptAssignment,
  submitAssignment,
  approveAssignment,
  rejectAssignment,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import { useAssignmentFlow } from './useAssignmentFlow'
import { useDivisionDragDrop } from './useDivisionDragDrop'

export interface DivisionApi {
  fetchChapterAssignments: typeof fetchChapterAssignments
  upsertChapterAssignments: typeof upsertChapterAssignments
  acceptAssignment: typeof acceptAssignment
  submitAssignment: typeof submitAssignment
  approveAssignment: typeof approveAssignment
  rejectAssignment: typeof rejectAssignment
  fetchProject: typeof fetchProject
  fetchProjectMembers: typeof fetchProjectMembers
  fetchWorkflowStatus: typeof fetchWorkflowStatus
  confirmDivision: typeof confirmDivision
}

export interface DivisionNotify {
  error: (msg: string, duration?: number | undefined) => void
  success: (msg: string) => void
  warning: (msg: string) => void
  info: (msg: string) => void
}

export interface DivisionRouteTarget {
  name: string
  params: Record<string, string>
  query?: Record<string, string>
}

export interface AssignRow {
  chapter_no: string
  title: string
  id?: string
  assignee_id?: string
  assignee_name?: string
  status?: TaskStatus | string
  children?: AssignRow[]
}

export interface MoveAction {
  kind: 'accept' | 'submit' | 'approve' | 'reject'
  successText: string
}

// flattenAssignmentNodes 和 sectionTitleOf 已移至 divisionUtils.ts（N9 拆分避免循环导入）
// 此处 re-export 保持模块级导出路径不变（契约守卫依赖）
export { flattenAssignmentNodes, sectionTitleOf } from './divisionUtils'

export function useDivisionBoard(
  projectId: string,
  deps: {
    api: DivisionApi
    notify: DivisionNotify
    routerPush: (to: DivisionRouteTarget) => void
    fetchCurrentUserRole: () => Promise<unknown>
  },
) {
  const { api, notify, routerPush, fetchCurrentUserRole } = deps
  const msgErr = (err: unknown, fallback: string) => {
    const m = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    notify.error(m || fallback)
  }

  const { isProjectOwner } = usePermission()

  const loading = ref(false)
  const loadError = ref('')
  const kanbanHistory = useUndoRedo<AssignmentItem[]>([])
  const items = kanbanHistory.state
  const projectOwnerId = ref('')

  const outline = ref<OutlineItem[]>([])
  const assignTree = ref<AssignmentNode[]>([])
  const members = ref<ProjectMember[]>([])
  const filterAssignee = ref<string | undefined>(undefined)
  const confirmingDivision = ref(false)

  const isOwner = computed(() => isProjectOwner(projectOwnerId.value))

  const assignColumns = [
    { title: '章节', key: 'chapter', dataIndex: 'chapter_no' },
    { title: '负责人', key: 'assignee', width: 220 },
    { title: '状态', key: 'status', width: 120 },
  ]

  const assigneeFilterOptions = computed(() => {
    const map = new Map<string, string>()
    items.value.forEach((item) => {
      if (item.assignee_id && item.assignee_name) {
        map.set(item.assignee_id, item.assignee_name)
      }
    })
    return Array.from(map.entries()).map(([value, label]) => ({ value, label }))
  })

  const filteredItems = computed(() => {
    if (!isOwner.value) {
      return items.value.filter((item) => item.assignee_id === currentUserId.value)
    }
    if (!filterAssignee.value) return items.value
    return items.value.filter((item) => item.assignee_id === filterAssignee.value)
  })

  const myTaskCount = computed(() =>
    items.value.filter(
      (item) => item.assignee_id === currentUserId.value && item.status !== 'approved',
    ).length,
  )

  const approvedCount = computed(
    () => items.value.filter((item) => item.status === 'approved').length,
  )

  const handleConfirmDivision = async () => {
    confirmingDivision.value = true
    try {
      await api.confirmDivision(projectId)
      notify.success('分工编制已完成，进入审阅')
      routerPush({ name: 'Review', params: { projectId } })
    } catch (err) {
      msgErr(err, '进入审阅失败，请确认分工编制已提交并审核')
    } finally { confirmingDivision.value = false }
  }

  const fetchOutline = async () => {
    try {
      const { data } = await api.fetchWorkflowStatus(projectId)
      if (data.code === 0) {
        outline.value = data.data?.outline || []
      }
    } catch { /* 静默失败 */ }
  }

  const fetchProjectOwner = async () => {
    try {
      const { data } = await api.fetchProject(projectId)
      if (data.code === 0) {
        projectOwnerId.value = data.data?.owner_id || ''
      }
    } catch { /* 静默失败 */ }
  }

  const fetchMembers = async () => {
    try {
      const { data } = await api.fetchProjectMembers(projectId)
      if (data.code === 0) {
        members.value = data.data?.items || []
      }
    } catch { /* 静默失败 */ }
  }

  const fetchAll = async () => {
    loading.value = true
    loadError.value = ''
    try {
      await Promise.all([
        assignmentFlow.fetchAssignments(),
        fetchOutline(),
        fetchProjectOwner(),
        fetchMembers(),
      ])
    } finally {
      loading.value = false
      kanbanHistory.reset(items.value)
    }
  }

  const goToGenerate = () => {
    routerPush({ name: 'Generate', params: { projectId } })
  }

  const assignmentFlow = useAssignmentFlow({
    api, notify, projectId, outline, assignTree, members, loading, loadError, items,
  })

  const dragDrop = useDivisionDragDrop({
    api, notify, items, kanbanHistory,
    fetchAssignments: assignmentFlow.fetchAssignments,
    routerPush, projectId,
  })

  onMounted(() => {
    fetchAll()
    fetchCurrentUserRole()
  })

  return {
    loading,
    loadError,
    items,
    isOwner,
    outline,
    assignTree,
    members,
    draftAssignees: assignmentFlow.draftAssignees,
    assigning: assignmentFlow.assigning,
    filterAssignee,
    assignColumns,
    memberOptions: assignmentFlow.memberOptions,
    filterMember: assignmentFlow.filterMember,
    assignRows: assignmentFlow.assignRows,
    assignableRows: assignmentFlow.assignableRows,
    changedItems: assignmentFlow.changedItems,
    changedCount: assignmentFlow.changedCount,
    assigneeFilterOptions,
    filteredItems,
    myTaskCount,
    approvedCount,
    confirmingDivision,
    handleConfirmDivision,
    syncDraftBaseline: assignmentFlow.syncDraftBaseline,
    fetchAssignments: assignmentFlow.fetchAssignments,
    fetchOutline,
    fetchProjectOwner,
    fetchMembers,
    fetchAll,
    handleAssign: assignmentFlow.handleAssign,
    handleSelectTask: dragDrop.handleSelectTask,
    resolveMoveAction: dragDrop.resolveMoveAction,
    handleMoveTask: dragDrop.handleMoveTask,
    handleKanbanUndo: dragDrop.handleKanbanUndo,
    handleKanbanRedo: dragDrop.handleKanbanRedo,
    goToGenerate,
  }
}
