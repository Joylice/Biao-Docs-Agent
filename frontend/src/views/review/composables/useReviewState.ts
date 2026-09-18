/**
 * useReviewState：审阅页面状态管理 composable
 *
 * 职责：
 * - 工作流状态加载与应用（chapters/outline/reviewFeedback/exportStatus）
 * - 分工树加载与融合（2026-09-03：分工模式下「提审章节直接进审阅页」）
 * - 提交人信息加载
 * - 废标风险加载
 * - 轮询管理（pollUntil/stopPolling）
 *
 * 数据口径：
 * - AI 生成模式（无分工）：审阅单元 = 工作流 state.chapters（章级）
 * - 分工模式（有 chapter_assignments）：审阅单元 = 分工章节（子节粒度），
 *   内容存 assignment.content_html；审核通过（approved）后由后端回写父章
 *   正式方案（state.chapters[父章号]）供全文预览 / Word 导出。
 */
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchWorkflowStatus,
  fetchChapterAssignments,
  fetchDisqualificationRisks as fetchDisqualificationRisksApi,
} from '@/api'
import type { WorkflowStatus, AssignmentNode } from '@/types'
import type { OutlineSection } from '@/types/outline'

export interface OutlineNode {
  chapter_no: string
  title: string
  sections?: OutlineSection[]
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

  /* ---------------- 分工数据（2026-09-03 融合） ---------------- */
  /** 分工树（章聚合行 + children 子节），来自 /chapter-assignments */
  const assignmentTree = ref<AssignmentNode[]>([])
  /** 扁平映射 chapter_no → 分工记录（章 + 子节） */
  const assignmentMap = ref<Record<string, AssignmentNode>>({})

  /** 是否存在分工（true = 分工驱动模式，审阅单元为分工章节；false = AI 生成模式） */
  const hasDivision = computed(
    () =>
      assignmentTree.value.length > 0 &&
      assignmentTree.value.some(
        (c) => (c.children?.length ?? 0) > 0 || Boolean(c.id),
      ),
  )

  /* ---------------- 轮询 ---------------- */
  let pollTimer: number | null = null
  const polling = computed(() => pollTimer !== null)

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /* ---------------- 分工加载 ---------------- */
  const fetchAssignments = async () => {
    try {
      const res = await fetchChapterAssignments(projectId)
      const items = (res.data?.data?.items ?? []) as AssignmentNode[]
      assignmentTree.value = items
      const map: Record<string, AssignmentNode> = {}
      const walk = (n: AssignmentNode) => {
        map[n.chapter_no] = n
        for (const child of n.children || []) walk(child)
      }
      for (const item of items) walk(item)
      assignmentMap.value = map
      // 兼容旧消费方：submitted_by_name → submitters
      const sm: Record<string, string> = {}
      for (const no of Object.keys(map)) {
        const name = map[no]?.submitted_by_name || map[no]?.assignee_name
        if (name) sm[no] = name
      }
      submitters.value = sm
    } catch {
      /* 降级：保留旧数据，AI 模式不受影响 */
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
      const keys = chapterKeys.value
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
    await fetchAssignments()
  }

  /* ---------------- 废标风险 ---------------- */
  const fetchDisqualificationRisks = async () => {
    try {
      const res = await fetchDisqualificationRisksApi(projectId)
      disqualificationRisks.value = res.data?.data?.risks || {}
    } catch { disqualificationRisks.value = {} }
  }

  /* ---------------- 计算属性 ---------------- */
  /**
   * 审阅单元编号：
   * - 分工模式：分工树中可审的分工章节（子节；章级分工退化保留章号）
   * - AI 模式：工作流正式方案 chapters（章级）
   */
  const chapterKeys = computed(() => {
    if (hasDivision.value) {
      const nos: string[] = []
      for (const ch of assignmentTree.value) {
        const subs = ch.children || []
        if (subs.length > 0) {
          for (const s of subs) nos.push(s.chapter_no)
        } else if (ch.id) {
          nos.push(ch.chapter_no)
        }
      }
      return nos
    }
    return Object.keys(chapters.value)
  })

  /** 正式方案章节（章级 state.chapters）——全文预览 / Word 导出使用 */
  const formalChapterKeys = computed(() => Object.keys(chapters.value))

  /** 分工原始状态（五态）；非分工章节返回 null */
  const rawStatusOf = (chapterNo: string): string | null =>
    hasDivision.value ? (assignmentMap.value[chapterNo]?.status ?? null) : null

  /** 分工记录 id（审阅动作定位）；无分工章节返回 null */
  const assignmentIdOf = (chapterNo: string): string | null => {
    if (!hasDivision.value) return null
    const node = assignmentMap.value[chapterNo]
    return node?.id ?? null
  }

  /** UI 三态：approved / rejected / pending */
  const chapterStatuses = computed<Record<string, string>>(() => {
    const statuses: Record<string, string> = {}
    for (const no of chapterKeys.value) {
      const raw = assignmentMap.value[no]?.status
      if (raw) {
        if (raw === 'approved') statuses[no] = 'approved'
        else if (raw === 'rejected') statuses[no] = 'rejected'
        else statuses[no] = 'pending'
      } else if (reviewFeedback.value[no]) {
        statuses[no] = 'rejected'
      } else if (exportStatus.value === 'done') {
        statuses[no] = 'approved'
      } else {
        statuses[no] = 'pending'
      }
    }
    return statuses
  })

  const approvedCount = computed(
    () => chapterKeys.value.filter((no) => chapterStatuses.value[no] === 'approved').length,
  )
  const rejectedCount = computed(
    () => chapterKeys.value.filter((no) => chapterStatuses.value[no] === 'rejected').length,
  )

  /** 章节标题：分工记录标题（章/子节）→ 大纲标题兜底 */
  const titleOf = (chapterNo: string): string => {
    const node = assignmentMap.value[chapterNo]
    if (node?.title) return node.title
    const c = outline.value.find((o) => o.chapter_no === chapterNo)
    if (c?.title) return c.title
    return ''
  }

  const submitterOf = (chapterNo: string): string => {
    const node = assignmentMap.value[chapterNo]
    if (hasDivision.value) return node?.assignee_name || '未分配'
    return submitters.value[chapterNo] || 'AI 生成/未分配'
  }

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
    // 分工数据
    assignmentTree,
    assignmentMap,
    hasDivision,
    // 方法
    fetchStatus,
    applyStatus,
    pollUntil,
    stopPolling,
    fetchAssignments,
    fetchSubmitters,
    fetchDisqualificationRisks,
    // 计算属性
    chapterKeys,
    formalChapterKeys,
    rawStatusOf,
    assignmentIdOf,
    chapterStatuses,
    approvedCount,
    rejectedCount,
    titleOf,
    submitterOf,
  }
}
