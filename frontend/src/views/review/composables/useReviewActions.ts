/**
 * useReviewActions：审阅页面操作 composable
 *
 * 职责：
 * - 审阅通过（handleApprove）
 * - 打回章节（handleReject）
 * - 导出弹窗管理（exportModalVisible/handleExport/handleExported）
 * - 返回修改（goToGenerate）
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { confirmReview } from '@/api'
import type { WorkflowStatus } from '@/types'

export function useReviewActions(options: {
  projectId: string
  getActiveChapter: () => string
  getReviewFeedback: () => Record<string, string>
  setReviewFeedback: (v: Record<string, string>) => void
  setExportStatus: (v: string) => void
  setExportStorageKey: (v: string) => void
  pollUntil: (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => void
}) {
  const {
    projectId,
    getActiveChapter,
    getReviewFeedback,
    setReviewFeedback,
    setExportStatus,
    setExportStorageKey,
    pollUntil,
  } = options

  const router = useRouter()

  /* ---------------- 状态 ---------------- */
  const approving = ref(false)
  const exportModalVisible = ref(false)

  /* ---------------- 审阅通过 ---------------- */
  const handleApprove = async () => {
    approving.value = true
    try {
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
    approving.value = true
    try {
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
