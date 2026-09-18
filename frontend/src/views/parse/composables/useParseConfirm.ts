import { computed, ref, onMounted } from 'vue'
import type { WorkflowStatus, GlossaryItem } from '@/types'
import { useSuccessButton } from '@/composables/useSuccessButton'
import type {
  fetchScorePoints,
  updateScorePoint,
  downloadProjectDocument,
  reparseDocument,
  fetchDocFormatRequirements,
  saveDocFormatRequirements,
  fetchDocDisqualificationClauses,
  saveDocDisqualificationClauses,
  fetchDocGlossary,
  fetchProjectDocuments,
  fetchWorkflowStatus,
  startWorkflow,
  confirmScorePoints,
} from '@/api'

export interface ScorePoint {
  id: string
  clause_no: string
  item: string
  score: number | null
  criteria: string | null
  is_star: boolean
  risk_level: string | null
  strategy: string | null
  confirmed: boolean
}

export interface TenderDocItem { id: string; title: string; status: string }

export interface FormatRequirementItem { key: string; category: string; requirement: string }

export interface DisqualificationClause {
  id: string
  clause_no: string
  title: string
  risk_category: string
  severity: string
  recommendation: string
  confirmed: boolean
}

export interface ParseConfirmApi {
  fetchScorePoints: typeof fetchScorePoints
  updateScorePoint: typeof updateScorePoint
  downloadProjectDocument: typeof downloadProjectDocument
  reparseDocument: typeof reparseDocument
  fetchDocFormatRequirements: typeof fetchDocFormatRequirements
  saveDocFormatRequirements: typeof saveDocFormatRequirements
  fetchDocDisqualificationClauses: typeof fetchDocDisqualificationClauses
  saveDocDisqualificationClauses: typeof saveDocDisqualificationClauses
  fetchDocGlossary: typeof fetchDocGlossary
  fetchProjectDocuments: typeof fetchProjectDocuments
  fetchWorkflowStatus: typeof fetchWorkflowStatus
  startWorkflow: typeof startWorkflow
  confirmScorePoints: typeof confirmScorePoints
}

export interface ParseConfirmNotify {
  error: (msg: string) => void
  success: (msg: string) => void
  warning: (msg: string) => void
  info: (msg: string) => void
  /** message.loading：返回关闭函数 */
  loading: (msg: string, duration?: number) => () => void
}

/**
 * useParseConfirm：招标解析确认页逻辑模型
 * - 数据域：评分点/招标文档/格式要求/废标条款/术语表 加载与更新
 * - 派生统计：确认进度/总分/高分风险/按钮可用性
 * - 行内防抖自动保存（1s 合并）+ 强制 flush 闸门
 * - 工作流推进：ensureScorePointInterrupt 轮询 → 保存确认闸门 → 生成大纲跳转
 * - 批量操作：批量确认（浮动栏）/ 批量策略（模态框）
 */
export function useParseConfirm(
  projectId: string,
  deps: {
    api: ParseConfirmApi
    notify: ParseConfirmNotify
    routerPush: (name: string, params: { projectId: string }) => void
  },
) {
  const { api, notify, routerPush } = deps
  const msgErr = (err: unknown, fallback: string) => {
    const m = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    notify.error(m || fallback)
  }

  /* ---------------- 状态 ---------------- */
  const activeTab = ref('score')
  const loading = ref(false)
  const loadError = ref('')
  const confirming = ref(false)
  const savingAll = ref(false)
  /** 行内防抖自动保存队列：id → 定时器（2026-08-25 B+C 优化：评分点 Tab 编辑即存） */
  const autoSaveTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const confirmAllLoading = ref(false)
  const batchStrategyOpen = ref(false)
  const batchStrategyLoading = ref(false)
  const batchStrategy = ref('')
  const scorePoints = ref<ScorePoint[]>([])
  const tenderDoc = ref<TenderDocItem | null>(null)
  const reparseLoading = ref(false)
  const selectedRowKeys = ref<string[]>([])
  const formatRequirements = ref<FormatRequirementItem[]>([])
  const formatSaving = ref(false)
  const disqualificationClauses = ref<DisqualificationClause[]>([])
  const disqualificationSaving = ref(false)
  const downloadTenderLoading = ref(false)
  const glossaryItems = ref<GlossaryItem[]>([])
  let formatKeySeq = 0

  // 批量确认成功反馈：按钮短暂显示 success 样式 + 勾选图标
  const { isSuccess: confirmSuccess, runWithSuccess: runBatchConfirm } = useSuccessButton()

  /* ---------------- 派生统计 ---------------- */
  const confirmedCount = computed(() => scorePoints.value.filter((p) => p.confirmed).length)
  const confirmedPercent = computed(() =>
    scorePoints.value.length === 0 ? 0 : Math.round((confirmedCount.value / scorePoints.value.length) * 100),
  )
  const totalScore = computed(() => scorePoints.value.reduce((sum, p) => sum + (p.score ?? 0), 0))
  const highRiskCount = computed(() => scorePoints.value.filter((p) => (p.score ?? 0) >= 20).length)
  const unconfirmedHighRiskCount = computed(() => scorePoints.value.filter((p) => !p.confirmed && (p.score ?? 0) >= 20).length)
  const canGenerate = computed(() => confirmedCount.value > 0)
  const canSaveConfirm = computed(() => confirmedCount.value > 0)
  const canReparse = computed(() => !!tenderDoc.value && ['parsed', 'failed'].includes(tenderDoc.value.status))

  /* ---------------- 格式要求 ---------------- */
  const handleAddFormatItem = () => {
    formatKeySeq += 1
    formatRequirements.value.push({ key: `new-${formatKeySeq}`, category: 'other', requirement: '' })
  }

  const handleRemoveFormatItem = (item: FormatRequirementItem) => {
    formatRequirements.value = formatRequirements.value.filter((it) => it.key !== item.key)
  }

  const handleSaveFormat = async () => {
    if (!tenderDoc.value) return
    const items = formatRequirements.value
      .map((it) => ({ category: it.category, requirement: it.requirement.trim() }))
      .filter((it) => it.requirement)
    formatSaving.value = true
    try {
      const res = await api.saveDocFormatRequirements(projectId, tenderDoc.value.id, items)
      if (res.data?.code !== 0) { notify.error(res.data?.message || '格式要求保存失败'); return }
      const saved = res.data?.data?.items || []
      formatRequirements.value = saved.map((it: { category: string; requirement: string }, i: number) => ({ key: `fmt-${i}`, ...it }))
      notify.success(`格式要求已保存（${saved.length} 条）`)
    } catch (err) {
      msgErr(err, '格式要求保存失败')
    } finally { formatSaving.value = false }
  }

  /* ---------------- 招标文档 ---------------- */
  const handleDownloadTender = async () => {
    if (!tenderDoc.value) return
    downloadTenderLoading.value = true
    try {
      const resp = await api.downloadProjectDocument(projectId, tenderDoc.value.id)
      const url = URL.createObjectURL(resp.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = tenderDoc.value.title || '招标文件'
      a.click()
      URL.revokeObjectURL(url)
    } catch { notify.error('下载失败，请重试') }
    finally { downloadTenderLoading.value = false }
  }

  /* ---------------- 废标条款 ---------------- */
  const handleDisqualificationConfirm = async (clause: DisqualificationClause, checked: boolean) => {
    if (!tenderDoc.value || disqualificationSaving.value) return
    const prev = clause.confirmed
    clause.confirmed = checked
    disqualificationSaving.value = true
    try {
      const res = await api.saveDocDisqualificationClauses(
        projectId,
        tenderDoc.value.id,
        disqualificationClauses.value.map((it) => ({ id: it.id, clause_no: it.clause_no, title: it.title, risk_category: it.risk_category, severity: it.severity, recommendation: it.recommendation, confirmed: it.confirmed })),
      )
      if (res.data?.code !== 0) { clause.confirmed = prev; notify.error(res.data?.message || '废标条款确认状态保存失败'); return }
      notify.success('已保存废标条款确认状态')
    } catch (err) {
      clause.confirmed = prev
      msgErr(err, '废标条款确认状态保存失败')
    } finally { disqualificationSaving.value = false }
  }

  /* ---------------- 数据加载 ---------------- */
  const fetchData = async () => {
    loading.value = true
    loadError.value = ''
    try {
      const spRes = await api.fetchScorePoints(projectId)
      scorePoints.value = spRes.data?.data || []
      const docRes = await api.fetchProjectDocuments(projectId, { doc_type: 'tender_file' })
      const docItems = docRes.data?.data?.items || []
      tenderDoc.value = docItems[0] || null
      if (tenderDoc.value) {
        const fmtRes = await api.fetchDocFormatRequirements(projectId, tenderDoc.value.id)
        const items = fmtRes.data?.data?.items || []
        formatRequirements.value = items.map((it: { category: string; requirement: string }, i: number) => ({ key: `fmt-${i}`, ...it }))
        try {
          const dqRes = await api.fetchDocDisqualificationClauses(projectId, tenderDoc.value.id)
          disqualificationClauses.value = dqRes.data?.data?.items || []
        } catch { disqualificationClauses.value = [] }
        try {
          const glRes = await api.fetchDocGlossary(projectId, tenderDoc.value.id)
          glossaryItems.value = glRes.data?.data?.items || []
        } catch { glossaryItems.value = [] }
      }
    } catch { loadError.value = '解析数据加载失败' }
    finally { loading.value = false }
  }

  /* ---------------- 重新解析 ---------------- */
  const handleReparse = async () => {
    if (!tenderDoc.value) return
    reparseLoading.value = true
    try {
      await api.reparseDocument(projectId, tenderDoc.value.id)
      notify.success('已发起重新解析，页面即将刷新')
      window.location.reload()
    } catch (err) {
      msgErr(err, '重新解析发起失败')
    } finally { reparseLoading.value = false }
  }

  /* ---------------- 行内防抖自动保存 ---------------- */
  /** 行内防抖自动保存（2026-08-25 B+C 优化）：1s 内合并同一行连续修改，静默落库 */
  const handleAutoSave = (row: ScorePoint) => {
    const prev = autoSaveTimers.get(row.id)
    if (prev) clearTimeout(prev)
    autoSaveTimers.set(
      row.id,
      setTimeout(async () => {
        autoSaveTimers.delete(row.id)
        try {
          const res = await api.updateScorePoint(projectId, row.id, {
            strategy: row.strategy,
            confirmed: row.confirmed,
          })
          if (res.data?.code !== 0) {
            notify.error(res.data?.message || '自动保存失败')
          }
        } catch {
          notify.error('自动保存失败')
        }
      }, 1000),
    )
  }

  /** 强制 flush 防抖队列中尚未落库的行（闸门/离开页面前调用，防丢数据） */
  const flushPendingSaves = async (): Promise<void> => {
    const pending = Array.from(autoSaveTimers.entries())
    if (pending.length === 0) return
    for (const [id, timer] of pending) {
      clearTimeout(timer)
      autoSaveTimers.delete(id)
      const row = scorePoints.value.find((p) => p.id === id)
      if (!row) continue
      try {
        await api.updateScorePoint(projectId, id, { strategy: row.strategy, confirmed: row.confirmed })
      } catch {
        notify.error(`评分点自动保存失败（${row.item || id}）`)
      }
    }
  }

  /* ---------------- 批量操作 ---------------- */
  /** 批量确认：作用于浮动栏勾选的评分点（仅处理其中未确认项） */
  const handleConfirmAll = async () => {
    const selected = new Set(selectedRowKeys.value)
    const pending = scorePoints.value.filter((p) => !p.confirmed && selected.has(p.id))
    if (pending.length === 0) {
      notify.info('所选评分点已全部确认')
      selectedRowKeys.value = []
      return
    }
    confirmAllLoading.value = true
    let errMsg = '批量确认失败，请重试'
    const ok = await runBatchConfirm(async () => {
      for (const p of pending) {
        const res = await api.updateScorePoint(projectId, p.id, { confirmed: true })
        if (res.data?.code !== 0) {
          errMsg = res.data?.message || '确认失败'
          throw new Error(errMsg)
        }
        p.confirmed = true
      }
    })
    confirmAllLoading.value = false
    if (ok) {
      notify.success(`已确认 ${pending.length} 条评分点`)
      // 延迟清空勾选：让浮动栏按钮短暂展示成功态（1.5s）后再收起
      window.setTimeout(() => { selectedRowKeys.value = [] }, 1500)
    } else {
      notify.error(errMsg)
    }
  }

  const handleApplyBatchStrategy = async () => {
    const strategy = batchStrategy.value.trim()
    if (!strategy) { notify.warning('请输入策略内容'); return }
    batchStrategyLoading.value = true
    try {
      for (const p of scorePoints.value) {
        const res = await api.updateScorePoint(projectId, p.id, { strategy })
        if (res.data?.code !== 0) { notify.error(res.data?.message || '应用失败'); return }
        p.strategy = strategy
      }
      notify.success(`已应用到全部 ${scorePoints.value.length} 条评分点`)
      batchStrategyOpen.value = false
    } catch { notify.error('批量修改失败，请重试') }
    finally { batchStrategyLoading.value = false }
  }

  /* ---------------- 工作流推进 ---------------- */
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

  const getWorkflowStatus = async (): Promise<WorkflowStatus | null> => {
    const res = await api.fetchWorkflowStatus(projectId)
    return res.data?.data || null
  }

  const ensureScorePointInterrupt = async (): Promise<boolean> => {
    let status = await getWorkflowStatus()
    if (status?.interrupt?.type === 'confirm_score_points') return true
    if (status?.interrupt) { notify.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
    const phase = status?.phase || 'init'
    if (phase === 'init') { await api.startWorkflow(projectId) }
    else if (phase !== 'confirm') { notify.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
    for (let i = 0; i < 60; i += 1) {
      await sleep(1000)
      status = await getWorkflowStatus()
      if (status?.interrupt?.type === 'confirm_score_points') return true
      if (status?.interrupt) { notify.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
      if (status?.error) { notify.error(`解析失败：${status.error}`); return false }
    }
    notify.error('等待解析超时，请刷新页面后重试')
    return false
  }

  /** 保存确认 = 流程闸门（2026-08-25 B+C 优化：不再循环写库，评分点 Tab 已自动保存）.
   *
   * 校验顺序：先 flush 防抖队列强制落库（兜底）→ 全部评分点已确认。
   * 通过后由「确认并生成大纲」推进工作流，本按钮仅做就绪校验与引导。
   */
  const handleSaveAll = async () => {
    if (scorePoints.value.length === 0) {
      notify.info('暂无评分点需要保存')
      return
    }
    savingAll.value = true
    try {
      // 1. 强制落库防抖队列中尚未提交的修改（防用户 1s 内点击导致丢数据）
      await flushPendingSaves()
      // 2. 全部评分点已确认
      if (confirmedCount.value !== scorePoints.value.length) {
        notify.warning(`还有 ${scorePoints.value.length - confirmedCount.value} 条评分点未确认`)
        return
      }
      notify.success('评分点已全部确认，可以生成大纲')
    } finally {
      savingAll.value = false
    }
  }

  const handleConfirm = async () => {
    confirming.value = true
    const hideLoading = notify.loading('正在启动解析工作流...', 0)
    try {
      // 推进工作流前强制落库防抖队列（评分点编辑即存，工作流从 DB 读最新状态）
      await flushPendingSaves()
      const ready = await ensureScorePointInterrupt()
      if (!ready) return
      hideLoading()
      await api.confirmScorePoints(projectId)
      notify.success('已确认，开始生成大纲...')
      routerPush('Generate', { projectId })
    } catch (err) {
      msgErr(err, '确认失败')
    } finally { hideLoading(); confirming.value = false }
  }

  onMounted(fetchData)

  return {
    activeTab,
    loading,
    loadError,
    confirming,
    savingAll,
    confirmAllLoading,
    batchStrategyOpen,
    batchStrategyLoading,
    batchStrategy,
    scorePoints,
    tenderDoc,
    reparseLoading,
    selectedRowKeys,
    formatRequirements,
    formatSaving,
    disqualificationClauses,
    disqualificationSaving,
    downloadTenderLoading,
    glossaryItems,
    confirmSuccess,
    confirmedCount,
    confirmedPercent,
    totalScore,
    highRiskCount,
    unconfirmedHighRiskCount,
    canGenerate,
    canSaveConfirm,
    canReparse,
    handleAddFormatItem,
    handleRemoveFormatItem,
    handleSaveFormat,
    handleDownloadTender,
    handleDisqualificationConfirm,
    fetchData,
    handleReparse,
    handleAutoSave,
    flushPendingSaves,
    handleConfirmAll,
    handleApplyBatchStrategy,
    handleSaveAll,
    handleConfirm,
  }
}
