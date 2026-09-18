/**
 * 任务状态机 composable（从 WordEditorPage.vue 拆分）
 *
 * 职责：
 * - 权限计算（owner/assignee/canEdit/isReadOnly/permissionHint）
 * - 任务状态展示（statusText/statusColor）
 * - 任务操作（accept/submit）
 * - 任务操作权限（canAccept/canSubmit）
 *
 * 审阅操作（approve/reject）已移至主审阅页，编辑器内不再提供审阅功能。
 */
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { message } from 'ant-design-vue'
import { acceptAssignment, submitAssignment } from '@/api'
import type { AssignmentItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'

export interface UseTaskWorkflowOptions {
  /** 项目 ID */
  projectId: string
  /** 当前分工任务（响应式 ref） */
  currentTask: Ref<AssignmentItem | null>
  /** 项目负责人 ID（响应式 ref） */
  projectOwnerId: Ref<string>
  /** 项目成员状态（响应式 ref） */
  isMember: Ref<boolean>
  /** 加载章节内容的回调（操作后刷新任务状态） */
  loadChapter: () => Promise<void>
}

export interface TaskWorkflowReturn {
  // --- 权限状态 ---
  /** 是否是项目负责人 */
  isOwner: ComputedRef<boolean>
  /** 是否是章节负责人 */
  isAssignee: ComputedRef<boolean>
  /** 是否可编辑 */
  canEdit: ComputedRef<boolean>
  /** 是否只读 */
  isReadOnly: ComputedRef<boolean>
  /** 权限提示 */
  permissionHint: ComputedRef<{ type: 'success' | 'error' | 'warning' | 'info'; text: string }>

  // --- 任务状态展示 ---
  /** 任务状态文本 */
  taskStatusText: ComputedRef<string>
  /** 任务状态颜色 */
  taskStatusColor: ComputedRef<string>

  // --- 任务操作权限 ---
  /** 是否可领取 */
  canAccept: ComputedRef<boolean>
  /** 是否可提交 */
  canSubmit: ComputedRef<boolean>

  // --- 任务操作状态 ---
  /** 领取中 */
  accepting: Ref<boolean>
  /** 提交中 */
  submittingTask: Ref<boolean>

  // --- 任务操作方法 ---
  /** 领取任务 */
  handleAccept: () => Promise<void>
  /** 提交审核 */
  handleSubmit: () => Promise<void>
}

export function useTaskWorkflow(options: UseTaskWorkflowOptions): TaskWorkflowReturn {
  const { projectId, currentTask, projectOwnerId, isMember, loadChapter } = options

  // --- 权限状态 ---
  const { isProjectOwner: checkProjectOwner } = usePermission()

  const isOwner = computed(() => checkProjectOwner(projectOwnerId.value))
  const isAssignee = computed(
    () => !!currentTask.value && currentTask.value.assignee_id === currentUserId.value,
  )

  /**
   * 内容锁定状态（2026-09-03 产品确认）：已提审 / 已通过章节内容锁定，不可再编辑。
   * - submitted（已提审）→ 审核期间锁定，待负责人打回（rejected）后才可继续修改
   * - approved（已通过）→ 终态锁定
   */
  const isContentLocked = computed(
    () => !!currentTask.value && ['submitted', 'approved'].includes(currentTask.value.status),
  )

  /**
   * 编辑权限（2026-09-03 按产品确认最终口径）：
   * - 仅「本人分工」的章节可编辑（assignee = 当前用户，owner 与成员口径一致）
   * - 已提审（submitted）/ 已通过（approved）→ 内容锁定，不可编辑
   * - owner 查看自己分工的章节 → 可编辑；查看他人分工 / 未分工章节 → 只读
   * - 项目成员查看他人负责章节 / 未分工章节 → 只读
   * - 非项目成员 → 只读（后端 403 兜底，前端仅控制 UI）
   */
  const canEdit = computed(() => isAssignee.value && !isContentLocked.value)

  /** 只读模式：不可编辑 或 路由标记 readonly */
  const isReadOnly = computed(() => !canEdit.value)

  /** 权限状态描述（用于编辑区顶部提示横幅） */
  const permissionHint = computed<{ type: 'success' | 'error' | 'warning' | 'info'; text: string }>(() => {
    if (!currentTask.value) return { type: 'warning', text: '该章节暂无分工记录，仅可查看' }
    if (isAssignee.value) {
      const status = currentTask.value.status
      if (status === 'pending') return { type: 'info', text: '章节可编辑（作为负责人，可先领取任务跟进状态）' }
      if (status === 'in_progress') return { type: 'success', text: '章节编制中，内容将自动保存' }
      if (status === 'rejected') return { type: 'error', text: '章节被打回，请修改后重新提交' }
      if (status === 'submitted') return { type: 'info', text: '已提交审核，内容已锁定，审核通过或打回前不可编辑' }
      if (status === 'approved') return { type: 'success', text: '审核已通过，内容已锁定' }
    }
    if (!isMember.value) return { type: 'warning', text: '您不是项目成员，仅可查看' }
    if (isOwner.value) return { type: 'info', text: '项目负责人仅可查看他人分工的章节，如需修改请调整分工或交由负责人提交' }
    const status = currentTask.value.status
    if (status === 'approved') return { type: 'success', text: '审核已通过，内容已锁定' }
    return { type: 'info', text: '本章节由其他成员分工负责，仅可查看' }
  })

  // --- 任务状态展示 ---
  const taskStatusText = computed(() => {
    const map: Record<string, string> = {
      pending: '待领取',
      in_progress: '编制中',
      rejected: '被打回',
      submitted: '已提审',
      approved: '已通过',
    }
    return map[currentTask.value?.status || ''] || ''
  })

  const taskStatusColor = computed(() => {
    const map: Record<string, string> = {
      pending: 'default',
      in_progress: 'processing',
      rejected: 'error',
      submitted: 'warning',
      approved: 'success',
    }
    return map[currentTask.value?.status || ''] || 'default'
  })

  // --- 任务操作权限 ---
  const canAccept = computed(
    () => isAssignee.value && currentTask.value?.status === 'pending',
  )
  const canSubmit = computed(
    () => isAssignee.value && currentTask.value?.status === 'in_progress',
  )

  // --- 任务操作状态 ---
  const accepting = ref(false)
  const submittingTask = ref(false)

  // --- 任务操作方法 ---
  const handleAccept = async () => {
    if (!currentTask.value) return
    accepting.value = true
    try {
      await acceptAssignment(projectId, currentTask.value.id)
      message.success('已领取任务')
      await loadChapter()
    } catch {
      message.error('领取失败')
    } finally {
      accepting.value = false
    }
  }

  const handleSubmit = async () => {
    if (!currentTask.value) return
    submittingTask.value = true
    try {
      await submitAssignment(projectId, currentTask.value.id)
      message.success('已提交审核')
      await loadChapter()
    } catch {
      message.error('提交失败')
    } finally {
      submittingTask.value = false
    }
  }

  return {
    // --- 权限状态 ---
    isOwner,
    isAssignee,
    canEdit,
    isReadOnly,
    permissionHint,

    // --- 任务状态展示 ---
    taskStatusText,
    taskStatusColor,

    // --- 任务操作权限 ---
    canAccept,
    canSubmit,

    // --- 任务操作状态 ---
    accepting,
    submittingTask,

    // --- 任务操作方法 ---
    handleAccept,
    handleSubmit,
  }
}