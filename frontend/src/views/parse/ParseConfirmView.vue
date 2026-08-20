<template>
  <div class="parse-confirm">
    <PageContainer
      title="招标解析确认"
      subtitle="确认评分点和技术需求，确认后生成方案大纲"
      :show-header="!embedded"
    >
      <LoadingSkeleton
        v-if="loading"
        :rows="5"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchData"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <EmptyState
        v-else-if="scorePoints.length === 0 && techRequirements.length === 0"
        description="暂无解析数据，请先在「招标解析」页上传招标文件"
      />

      <template v-else>
        <!-- 顶部统计 -->
        <ParseSummaryCard
          :confirmed-percent="confirmedPercent"
          :confirmed-count="confirmedCount"
          :total="scorePoints.length"
          :total-score="totalScore"
          :high-risk-count="highRiskCount"
          class="mb-4"
        />

        <!-- Tab 面板 -->
        <a-tabs
          v-model:activeKey="activeTab"
          class="parse-confirm__tabs"
        >
          <a-tab-pane
            key="score"
            tab="评分点"
          >
            <ParseScoreTable
              :score-points="scorePoints"
              :selected-row-keys="selectedRowKeys"
              :saving-id="savingId"
              :reparse-loading="reparseLoading"
              :download-tender-loading="downloadTenderLoading"
              :tender-doc="tenderDoc"
              :can-reparse="canReparse"
              @update:selected-row-keys="selectedRowKeys = $event"
              @save-row="handleSaveRow"
              @open-batch-strategy="batchStrategyOpen = true"
              @reparse="handleReparse"
              @download-tender="handleDownloadTender"
            />
          </a-tab-pane>

          <a-tab-pane
            key="tech"
            tab="技术需求"
          >
            <ParseTechTable
              :tech-requirements="techRequirements"
              :generate-loading="generateLoading"
              :selected-count="selectedRowKeys.length"
              @generate="handleGenerateRequirements"
            />
          </a-tab-pane>

          <a-tab-pane
            v-if="tenderDoc"
            key="format"
            tab="格式要求"
          >
            <ParseFormatPanel
              :format-requirements="formatRequirements"
              :format-saving="formatSaving"
              @add-item="handleAddFormatItem"
              @remove-item="handleRemoveFormatItem"
              @save="handleSaveFormat"
            />
          </a-tab-pane>

          <a-tab-pane
            v-if="tenderDoc"
            key="disqualification"
            tab="废标风险"
          >
            <ParseDisqualificationPanel
              :clauses="disqualificationClauses"
              :saving="disqualificationSaving"
              @checked="handleDisqualificationConfirm"
            />
          </a-tab-pane>
        </a-tabs>

        <!-- 操作按钮 -->
        <div class="parse-confirm__actions">
          <a-button
            type="primary"
            :loading="confirming"
            @click="handleConfirm"
          >
            确认并生成大纲
          </a-button>
        </div>
      </template>
    </PageContainer>

    <!-- 批量修改策略 -->
    <a-modal
      v-model:open="batchStrategyOpen"
      title="批量修改应对策略"
      :ok-text="`应用到全部 ${scorePoints.length} 条`"
      :confirm-loading="batchStrategyLoading"
      @ok="handleApplyBatchStrategy"
    >
      <a-textarea
        v-model:value="batchStrategy"
        :rows="4"
        placeholder="输入统一的应对策略模板，将应用到所有评分点"
      />
    </a-modal>

    <!-- 批量操作浮动栏：评分点 Tab 且有勾选时浮现 -->
    <transition name="batch-bar">
      <BatchActionBar
        v-if="activeTab === 'score' && selectedRowKeys.length > 0"
        :count="selectedRowKeys.length"
        :loading="confirmAllLoading"
        :success="confirmSuccess"
        @confirm="handleConfirmAll"
        @clear="selectedRowKeys = []"
      />
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useSuccessButton } from '@/composables/useSuccessButton'
import ParseSummaryCard from './components/ParseSummaryCard.vue'
import ParseScoreTable from './components/ParseScoreTable.vue'
import ParseTechTable from './components/ParseTechTable.vue'
import ParseFormatPanel from './components/ParseFormatPanel.vue'
import ParseDisqualificationPanel from './components/ParseDisqualificationPanel.vue'
import BatchActionBar from './components/BatchActionBar.vue'

interface ScorePoint {
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

interface TenderDocItem { id: string; title: string; status: string }

interface TechRequirement {
  id: string
  seq: number
  description: string
  category: string | null
  is_mandatory: boolean
  source?: string | null
  related_sp?: { clause_no: string; item: string } | null
}

interface FormatRequirementItem { key: string; category: string; requirement: string }

interface DisqualificationClause {
  id: string
  clause_no: string
  title: string
  risk_category: string
  severity: string
  recommendation: string
  confirmed: boolean
}

interface WorkflowStatus { phase: string; error: string; interrupt: { type: string } | null }

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const activeTab = ref('score')
const loading = ref(false)
const loadError = ref('')
const confirming = ref(false)
const savingId = ref('')
const confirmAllLoading = ref(false)
const batchStrategyOpen = ref(false)
const batchStrategyLoading = ref(false)
const batchStrategy = ref('')
const scorePoints = ref<ScorePoint[]>([])
const techRequirements = ref<TechRequirement[]>([])
const tenderDoc = ref<TenderDocItem | null>(null)
const reparseLoading = ref(false)
const selectedRowKeys = ref<string[]>([])
const generateLoading = ref(false)
const formatRequirements = ref<FormatRequirementItem[]>([])
const formatSaving = ref(false)
const disqualificationClauses = ref<DisqualificationClause[]>([])
const disqualificationSaving = ref(false)
const downloadTenderLoading = ref(false)
let formatKeySeq = 0

// 批量确认成功反馈：按钮短暂显示 success 样式 + 勾选图标
const { isSuccess: confirmSuccess, runWithSuccess: runBatchConfirm } = useSuccessButton()

const confirmedCount = computed(() => scorePoints.value.filter((p) => p.confirmed).length)
const confirmedPercent = computed(() =>
  scorePoints.value.length === 0 ? 0 : Math.round((confirmedCount.value / scorePoints.value.length) * 100),
)
const totalScore = computed(() => scorePoints.value.reduce((sum, p) => sum + (p.score ?? 0), 0))
const highRiskCount = computed(() => scorePoints.value.filter((p) => (p.score ?? 0) >= 20).length)
const canReparse = computed(() => !!tenderDoc.value && ['parsed', 'failed'].includes(tenderDoc.value.status))

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
    const res = await api.put(`/projects/${projectId}/documents/${tenderDoc.value.id}/format-requirements`, { format_requirements: items })
    if (res.data?.code !== 0) { message.error(res.data?.message || '格式要求保存失败'); return }
    const saved = res.data?.data?.items || []
    formatRequirements.value = saved.map((it: { category: string; requirement: string }, i: number) => ({ key: `fmt-${i}`, ...it }))
    message.success(`格式要求已保存（${saved.length} 条）`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '格式要求保存失败')
  } finally { formatSaving.value = false }
}

const handleDownloadTender = async () => {
  if (!tenderDoc.value) return
  downloadTenderLoading.value = true
  try {
    const resp = await api.get(`/projects/${projectId}/documents/${tenderDoc.value.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = tenderDoc.value.title || '招标文件'
    a.click()
    URL.revokeObjectURL(url)
  } catch { message.error('下载失败，请重试') }
  finally { downloadTenderLoading.value = false }
}

const handleDisqualificationConfirm = async (clause: DisqualificationClause, checked: boolean) => {
  if (!tenderDoc.value || disqualificationSaving.value) return
  const prev = clause.confirmed
  clause.confirmed = checked
  disqualificationSaving.value = true
  try {
    const res = await api.put(`/projects/${projectId}/documents/${tenderDoc.value.id}/disqualification-clauses`, {
      items: disqualificationClauses.value.map((it) => ({ id: it.id, clause_no: it.clause_no, title: it.title, risk_category: it.risk_category, severity: it.severity, recommendation: it.recommendation, confirmed: it.confirmed })),
    })
    if (res.data?.code !== 0) { clause.confirmed = prev; message.error(res.data?.message || '废标条款确认状态保存失败'); return }
    message.success('已保存废标条款确认状态')
  } catch (err) {
    clause.confirmed = prev
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '废标条款确认状态保存失败')
  } finally { disqualificationSaving.value = false }
}

const fetchData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [spRes, trRes] = await Promise.all([
      api.get(`/projects/${projectId}/score-points`),
      // 获取全部技术需求（含未关联评分点的），表格中显示关联状态
      api.get(`/projects/${projectId}/requirements`),
    ])
    scorePoints.value = spRes.data?.data || []
    techRequirements.value = trRes.data?.data || []
    const docRes = await api.get(`/projects/${projectId}/documents`, { params: { doc_type: 'tender_file' } })
    const docItems = docRes.data?.data?.items || docRes.data?.data || []
    tenderDoc.value = docItems[0] || null
    if (tenderDoc.value) {
      const fmtRes = await api.get(`/projects/${projectId}/documents/${tenderDoc.value.id}/format-requirements`)
      const items = fmtRes.data?.data?.items || []
      formatRequirements.value = items.map((it: { category: string; requirement: string }, i: number) => ({ key: `fmt-${i}`, ...it }))
      try {
        const dqRes = await api.get(`/projects/${projectId}/documents/${tenderDoc.value.id}/disqualification-clauses`)
        disqualificationClauses.value = dqRes.data?.data?.items || []
      } catch { disqualificationClauses.value = [] }
    }
  } catch { loadError.value = '解析数据加载失败' }
  finally { loading.value = false }
}

const handleGenerateRequirements = async () => {
  generateLoading.value = true
  try {
    // 确定用于生成的评分点ID：优先用选中的，未选中时用全部已确认的
    let spIds = selectedRowKeys.value
    if (spIds.length === 0) {
      spIds = scorePoints.value.filter((p) => p.confirmed).map((p) => p.id)
    }
    if (spIds.length === 0) {
      message.warning('请先确认至少一条评分点，或选中评分点后再生成技术需求')
      generateLoading.value = false
      return
    }
    const body = { score_point_ids: spIds }
    const res = await api.post(`/projects/${projectId}/requirements/generate`, body)
    if (res.data?.code !== 0) { message.error(res.data?.message || '技术需求生成失败'); return }
    const data = res.data?.data || {}
    message.success(`已生成 ${data.total} 条需求，其中 ${data.mapped} 条关联到评分点`)
    // 获取全部技术需求（含未关联的），表格中显示关联状态
    const trRes = await api.get(`/projects/${projectId}/requirements`)
    techRequirements.value = trRes.data?.data || []
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '技术需求生成失败')
  } finally { generateLoading.value = false }
}

const handleReparse = async () => {
  if (!tenderDoc.value) return
  reparseLoading.value = true
  try {
    await api.post(`/projects/${projectId}/documents/${tenderDoc.value.id}/reparse`)
    message.success('已发起重新解析，页面即将刷新')
    window.location.reload()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '重新解析发起失败')
  } finally { reparseLoading.value = false }
}

const handleSaveRow = async (row: ScorePoint) => {
  savingId.value = row.id
  try {
    const res = await api.put(`/projects/${projectId}/score-points/${row.id}`, { strategy: row.strategy, confirmed: row.confirmed })
    if (res.data?.code !== 0) { message.error(res.data?.message || '保存失败'); return }
    message.success('已保存')
  } catch { message.error('保存失败') }
  finally { savingId.value = '' }
}

/** 批量确认：作用于浮动栏勾选的评分点（仅处理其中未确认项） */
const handleConfirmAll = async () => {
  const selected = new Set(selectedRowKeys.value)
  const pending = scorePoints.value.filter((p) => !p.confirmed && selected.has(p.id))
  if (pending.length === 0) {
    message.info('所选评分点已全部确认')
    selectedRowKeys.value = []
    return
  }
  confirmAllLoading.value = true
  let errMsg = '批量确认失败，请重试'
  const ok = await runBatchConfirm(async () => {
    for (const p of pending) {
      const res = await api.put(`/projects/${projectId}/score-points/${p.id}`, { confirmed: true })
      if (res.data?.code !== 0) {
        errMsg = res.data?.message || '确认失败'
        throw new Error(errMsg)
      }
      p.confirmed = true
    }
  })
  confirmAllLoading.value = false
  if (ok) {
    message.success(`已确认 ${pending.length} 条评分点`)
    // 延迟清空勾选：让浮动栏按钮短暂展示成功态（1.5s）后再收起
    window.setTimeout(() => { selectedRowKeys.value = [] }, 1500)
  } else {
    message.error(errMsg)
  }
}

const handleApplyBatchStrategy = async () => {
  const strategy = batchStrategy.value.trim()
  if (!strategy) { message.warning('请输入策略内容'); return }
  batchStrategyLoading.value = true
  try {
    for (const p of scorePoints.value) {
      const res = await api.put(`/projects/${projectId}/score-points/${p.id}`, { strategy })
      if (res.data?.code !== 0) { message.error(res.data?.message || '应用失败'); return }
      p.strategy = strategy
    }
    message.success(`已应用到全部 ${scorePoints.value.length} 条评分点`)
    batchStrategyOpen.value = false
  } catch { message.error('批量修改失败，请重试') }
  finally { batchStrategyLoading.value = false }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const getWorkflowStatus = async (): Promise<WorkflowStatus | null> => {
  const res = await api.get(`/projects/${projectId}/workflow/status`)
  return res.data?.data || null
}

const ensureScorePointInterrupt = async (): Promise<boolean> => {
  let status = await getWorkflowStatus()
  if (status?.interrupt?.type === 'confirm_score_points') return true
  if (status?.interrupt) { message.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
  const phase = status?.phase || 'init'
  if (phase === 'init') { await api.post(`/projects/${projectId}/workflow/start`) }
  else if (phase !== 'confirm') { message.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
  for (let i = 0; i < 60; i += 1) {
    await sleep(1000)
    status = await getWorkflowStatus()
    if (status?.interrupt?.type === 'confirm_score_points') return true
    if (status?.interrupt) { message.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
    if (status?.error) { message.error(`解析失败：${status.error}`); return false }
  }
  message.error('等待解析超时，请刷新页面后重试')
  return false
}

const handleConfirm = async () => {
  confirming.value = true
  const hideLoading = message.loading('正在启动解析工作流...', 0)
  try {
    const ready = await ensureScorePointInterrupt()
    if (!ready) return
    hideLoading()
    await api.post(`/projects/${projectId}/workflow/confirm-score-points`)
    message.success('已确认，开始生成大纲...')
    router.push({ name: 'Generate', params: { projectId } })
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '确认失败')
  } finally { hideLoading(); confirming.value = false }
}

onMounted(fetchData)
</script>

<style scoped>
.parse-confirm { width: 100%; }
.mb-4 { margin-bottom: 16px; }

.parse-confirm__tabs {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 0 16px;
  margin-bottom: 16px;
}

.parse-confirm__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

/* 批量操作浮动栏进入/退出过渡：淡入 + 上移（transform 需保留 translateX(-50%) 居中） */
.batch-bar-enter-active,
.batch-bar-leave-active {
  transition: opacity var(--transition-normal), transform var(--transition-normal);
}

.batch-bar-enter-from,
.batch-bar-leave-to {
  opacity: 0;
  transform: translate(-50%, 16px);
}

.batch-bar-enter-to,
.batch-bar-leave-from {
  opacity: 1;
  transform: translate(-50%, 0);
}
</style>
