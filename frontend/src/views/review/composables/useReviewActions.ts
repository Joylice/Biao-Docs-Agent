/**
 * useReviewActions：审阅页面操作 composable
 *
 * 职责：
 * - 审阅通过（handleApprove）：分工章节走 assignment 审核（回写正式方案）；
 *   AI 生成章节走 workflow confirm-review（通过后触发导出）
 * - 打回章节（handleReject）：分工章节回退成员重编；AI 章节按意见重写/回派
 * - 导出弹窗管理（exportModalVisible/handleExport/handleExported）
 * - 返回修改（goToGenerate）
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { confirmReview, approveAssignment, rejectAssignment } from '@/api'
import type { WorkflowStatus } from '@/types'

export function useReviewActions(options: {
  projectId: string
  getActiveChapter: () => string
  getReviewFeedback: () => Record<string, string>
  setReviewFeedback: (v: Record<string, string>) => void
  setExportStatus: (v: string) => void
  setExportStorageKey: (v: string) => void
  pollUntil: (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => void
  /** 当前章节分工记录 id；null = 非分工章节（AI 模式） */
  getAssignmentId: () => string | null
  /** 分工审核动作成功后刷新（status + assignments），由页面注入 */
  refreshDivisionData: () => Promise<void>
}) {
  const {
    projectId,
    getActiveChapter,
    getReviewFeedback,
    setReviewFeedback,
    setExportStatus,
    setExportStorageKey,
    pollUntil,
    getAssignmentId,
    refreshDivisionData,
  } = options

  const router = useRouter()

  /* ---------------- 状态 ---------------- */
  const approving = ref(false)
  const exportModalVisible = ref(false)

  /* ---------------- 审阅通过 ---------------- */
  const handleApprove = async () => {
    const assignmentId = getAssignmentId()
    approving.value = true
    try {
      if (assignmentId) {
        // 分工章节：assignment 审核通过（后端回写正式方案 state.chapters）
        const res = await approveAssignment(projectId, assignmentId)
        if (res.data?.code !== 0) { message.error(res.data?.message || '审核通过失败'); return }
        message.success('审核通过，内容已并入正式方案')
        await refreshDivisionData()
        return
      }
      // AI 生成章节：整稿审阅确认 → 触发导出
      const res = await confirmReview(projectId, { action: 'approved' })
      if (res.data?.code !== 0) { message.error(res.data?.message || '审阅确认失败'); return }
      message.success('审阅通过，正在生成导出文档...')
      pollUntil(
        (data) => data.export_status === 'done',
        () => message.success('导出完成，可下载文档'),
      )
    } catch { message.error('审阅确认失败') }
    finally { approving.value = false }
  }

  /* ---------------- 打回章节 ---------------- */
  const handleReject = async (comment: string) => {
    const assignmentId = getAssignmentId()
    approving.value = true
    try {
      if (assignmentId) {
        // 分工章节：打回 → 成员重编后可重新提审
        const res = await rejectAssignment(projectId, assignmentId, comment)
        if (res.data?.code !== 0) { message.error(res.data?.message || '打回失败'); return }
        message.success(`章节 ${getActiveChapter()} 已打回修改`)
        await refreshDivisionData()
        return
      }
      // AI 生成章节：按意见回派/重写
      const res = await confirmReview(projectId, {
        action: 'feedback',
        feedback: { [getActiveChapter()]: comment },
      })
      if (res.data?.code !== 0) { message.error(res.data?.message || '打回失败'); return }
      setReviewFeedback({ ...getReviewFeedback(), [getActiveChapter()]: comment })
      message.success(`章节 ${getActiveChapter()} 已打回修改`)
    } catch (err) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
      message.error(msg || '打回失败')
    } finally {
      approving.value = false
    }
  }

  /* ---------------- 导出 ---------------- */
  const handleExport = () => {
    exportModalVisible.value = true
  }

  const handleExported = (storageKey: string) => {
    setExportStorageKey(storageKey)
    setExportStatus('done')
  }

  /* ---------------- 返回修改 ---------------- */
  const goToGenerate = () => router.push({ name: 'Generate', params: { projectId } })

  return {
    approving,
    exportModalVisible,
    handleApprove,
    handleReject,
    handleExport,
    handleExported,
    goToGenerate,
  }
}
