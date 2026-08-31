/**
 * 任务状态机 composable（从 WordEditorPage.vue 拆分）
 *
 * 职责：
 * - 权限计算（owner/assignee/canEdit/isReadOnly/permissionHint）
 * - 任务状态展示（statusText/statusColor）
 * - 任务操作（accept/submit/approve/reject）
 * - 任务操作权限（canAccept/canSubmit/canApprove/canReject）
 */
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { message } from 'ant-design-vue'
import { acceptAssignment, submitAssignment, approveAssignment, rejectAssignment } from '@/api'
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
  /** 是否可审核通过 */
  canApprove: ComputedRef<boolean>
  /** 是否可打回 */
  canReject: ComputedRef<boolean>

  // --- 任务操作状态 ---
  /** 领取中 */
  accepting: Ref<boolean>
  /** 提交中 */
  submittingTask: Ref<boolean>
  /** 审核通过中 */
  approving: Ref<boolean>
  /** 打回中 */
  rejectingTask: Ref<boolean>
  /** 打回弹窗显隐 */
  showRejectModal: Ref<boolean>
  /** 打回原因 */
  rejectComment: Ref<string>

  // --- 任务操作方法 ---
  /** 领取任务 */
  handleAccept: () => Promise<void>
  /** 提交审核 */
  handleSubmit: () => Promise<void>
  /** 审核通过 */
  handleApprove: () => Promise<void>
  /** 打回 */
  handleReject: () => Promise<void>
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
   * 编辑权限（2026-08-26 按产品确认放宽）：
   * - 无分工任务 → 只读
   * - 项目负责人（owner）→ 只读（分配者/审核者视角，不参与编制）
   * - 项目成员（含 assignee 及其他成员）且有分工记录 → 可编辑
   * - 非项目成员 → 只读（后端 403 兜底，前端仅控制 UI）
   */
  const canEdit = computed(() => {
    if (!currentTask.value) return false
    if (isOwner.value) return false
    if (!isMember.value) return false
    return true
  })

  /** 只读模式：不可编辑 或 路由标记 readonly */
  const isReadOnly = computed(() => !canEdit.value)

  /** 权限状态描述（用于编辑区顶部提示横幅） */
  const permissionHint = computed<{ type: 'success' | 'error' | 'warning' | 'info'; text: string }>(() => {
    if (!currentTask.value) return { type: 'warning', text: '该章节暂无分工记录，仅可查看' }
    if (isOwner.value) return { type: 'info', text: '项目负责人仅可查看，章节内容由项目成员编制' }
    if (!isMember.value) return { type: 'warning', text: '您不是项目成员，仅可查看' }
    if (isAssignee.value) {
      const status = currentTask.value.status
      if (status === 'pending') return { type: 'info', text: '章节可编辑（作为负责人，可先领取任务跟进状态）' }
      if (status === 'in_progress') return { type: 'success', text: '章节编制中，内容将自动保存' }
      if (status === 'rejected') return { type: 'error', text: '章节被打回，请修改后重新提交' }
      if (status === 'submitted') return { type: 'info', text: '已提交审核，等待项目负责人审核' }
      if (status === 'approved') return { type: 'success', text: '审核已通过，内容已锁定' }
    }
    const status = currentTask.value.status
    if (status === 'approved') return { type: 'success', text: '审核已通过，内容已锁定' }
    return { type: 'success', text: '您作为项目成员可编辑本章节，内容将自动保存' }
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
  const canApprove = computed(() => isOwner.value && currentTask.value?.status === 'submitted')
  const canReject = computed(() => isOwner.value && currentTask.value?.status === 'submitted')

  // --- 任务操作状态 ---
  const accepting = ref(false)
  const submittingTask = ref(false)
  const approving = ref(false)
  const rejectingTask = ref(false)
  const showRejectModal = ref(false)
  const rejectComment = ref('')

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

  const handleApprove = async () => {
    if (!currentTask.value) return
    approving.value = true
    try {
      await approveAssignment(projectId, currentTask.value.id)
      message.success('审核通过')
      await loadChapter()
    } catch {
      message.error('操作失败')
    } finally {
      approving.value = false
    }
  }

  const handleReject = async () => {
    if (!currentTask.value) return
    rejectingTask.value = true
    try {
      await rejectAssignment(projectId, currentTask.value.id, rejectComment.value || '审核不通过')
      message.success('已打回')
      showRejectModal.value = false
      rejectComment.value = ''
      await loadChapter()
    } catch {
      message.error('操作失败')
    } finally {
      rejectingTask.value = false
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
    canApprove,
    canReject,

    // --- 任务操作状态 ---
    accepting,
    submittingTask,
    approving,
    rejectingTask,
    showRejectModal,
    rejectComment,

    // --- 任务操作方法 ---
    handleAccept,
    handleSubmit,
    handleApprove,
    handleReject,
  }
}