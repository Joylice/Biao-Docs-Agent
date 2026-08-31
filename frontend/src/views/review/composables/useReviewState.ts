/**
 * useReviewState：审阅页面状态管理 composable
 *
 * 职责：
 * - 工作流状态加载与应用（chapters/outline/reviewFeedback/exportStatus）
 * - 提交人信息加载
 * - 废标风险加载
 * - 轮询管理（pollUntil/stopPolling）
 */
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchWorkflowStatus,
  fetchChapterAssignments,
  fetchDisqualificationRisks as fetchDisqualificationRisksApi,
} from '@/api'
import type { WorkflowStatus } from '@/types'

export interface OutlineNode {
  chapter_no: string
  title: string
  sections?: string[]
}

export interface RiskItem {
  clause_no: string
  title: string
  severity: string
  risk_category: string
  recommendation: string
}

export function useReviewState(projectId: string) {
  /* ---------------- 基础状态 ---------------- */
  const loading = ref(false)
  const loadError = ref('')
  const chapters = ref<Record<string, string>>({})
  const outline = ref<OutlineNode[]>([])
  const submitters = ref<Record<string, string>>({})
  const reviewFeedback = ref<Record<string, string>>({})
  const exportStatus = ref('')
  const exportStorageKey = ref('')
  const disqualificationRisks = ref<Record<string, RiskItem[]>>({})

  /* ---------------- 轮询 ---------------- */
  let pollTimer: number | null = null
  const polling = computed(() => pollTimer !== null)

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /* ---------------- 工作流状态 ---------------- */
  const fetchStatus = async (): Promise<WorkflowStatus | undefined> => {
    const res = await fetchWorkflowStatus(projectId)
    return res.data?.data
  }

  const applyStatus = (data: WorkflowStatus, getActiveChapter?: () => string, setActiveChapter?: (v: string) => void, getExpandedKeys?: () => string[], setExpandedKeys?: (v: string[]) => void, getRouteQueryChapter?: () => string) => {
    chapters.value = data.chapters || {}
    outline.value = (data.outline || []) as OutlineNode[]
    reviewFeedback.value = data.review_feedback || {}
    exportStatus.value = data.export_status || ''
    exportStorageKey.value = data.export_storage_key || ''

    if (getActiveChapter && setActiveChapter && !getActiveChapter()) {
      const queryChapter = getRouteQueryChapter?.() || ''
      const keys = Object.keys(chapters.value)
      setActiveChapter(queryChapter && keys.includes(queryChapter) ? queryChapter : keys[0] || '')
    }
    if (getExpandedKeys && setExpandedKeys && getExpandedKeys().length === 0) {
      setExpandedKeys(outline.value.map((c) => c.chapter_no))
    }
  }

  const pollUntil = (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => {
    stopPolling()
    let attempts = 0
    pollTimer = window.setInterval(async () => {
      attempts += 1
      try {
        const data = await fetchStatus()
        if (!data) return
        chapters.value = data.chapters || {}
        outline.value = (data.outline || []) as OutlineNode[]
        reviewFeedback.value = data.review_feedback || {}
        exportStatus.value = data.export_status || ''
        exportStorageKey.value = data.export_storage_key || ''
        if (data.error) { stopPolling(); message.error(data.error); return }
        if (until(data)) { stopPolling(); onDone?.(data) }
        else if (attempts >= 90) { stopPolling(); message.warning('等待超时，请稍后手动刷新') }
      } catch { /* 重试 */ }
    }, 2000)
  }

  /* ---------------- 提交人 ---------------- */
  const fetchSubmitters = async () => {
    try {
      const res = await fetchChapterAssignments(projectId)
      const items = (res.data?.data?.items || []) as { chapter_no: string; submitted_by_name?: string }[]
      const map: Record<string, string> = {}
      for (const it of items) { if (it.submitted_by_name) map[it.chapter_no] = it.submitted_by_name }
      submitters.value = map
    } catch { /* 降级 */ }
  }

  /* ---------------- 废标风险 ---------------- */
  const fetchDisqualificationRisks = async () => {
    try {
      const res = await fetchDisqualificationRisksApi(projectId)
      disqualificationRisks.value = res.data?.data?.risks || {}
    } catch { disqualificationRisks.value = {} }
  }

  /* ---------------- 计算属性 ---------------- */
  const chapterKeys = computed(() => Object.keys(chapters.value))

  const chapterStatuses = computed<Record<string, string>>(() => {
    const statuses: Record<string, string> = {}
    chapterKeys.value.forEach((no) => {
      if (reviewFeedback.value[no]) {
        statuses[no] = 'rejected'
      } else if (exportStatus.value === 'done') {
        statuses[no] = 'approved'
      } else {
        statuses[no] = 'pending'
      }
    })
    return statuses
  })

  const approvedCount = computed(
    () => chapterKeys.value.filter((no) => chapterStatuses.value[no] === 'approved').length,
  )
  const rejectedCount = computed(
    () => chapterKeys.value.filter((no) => chapterStatuses.value[no] === 'rejected').length,
  )

  const submitterOf = (chapterNo: string): string => submitters.value[chapterNo] || 'AI 生成/未分配'

  return {
    // 状态
    loading,
    loadError,
    chapters,
    outline,
    submitters,
    reviewFeedback,
    exportStatus,
    exportStorageKey,
    disqualificationRisks,
    polling,
    // 方法
    fetchStatus,
    applyStatus,
    pollUntil,
    stopPolling,
    fetchSubmitters,
    fetchDisqualificationRisks,
    // 计算属性
    chapterKeys,
    chapterStatuses,
    approvedCount,
    rejectedCount,
    submitterOf,
  }
}
