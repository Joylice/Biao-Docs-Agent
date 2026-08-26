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
              :reparse-loading="reparseLoading"
              :download-tender-loading="downloadTenderLoading"
              :tender-doc="tenderDoc"
              :can-reparse="canReparse"
              @update:selected-row-keys="selectedRowKeys = $event"
              @auto-save="handleAutoSave"
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
              :confirmed-count="confirmedCount"
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

        <!-- 固定底部操作栏 -->
        <div class="parse-confirm__footer">
          <div class="parse-confirm__footer-left">
            <!-- 确认进度 -->
            <div class="parse-confirm__progress">
              <span class="parse-confirm__progress-label">确认进度</span>
              <a-progress
                :percent="confirmedPercent"
                :show-info="false"
                size="small"
                class="parse-confirm__progress-bar"
              />
              <span class="parse-confirm__progress-text">
                {{ confirmedCount }} / {{ scorePoints.length }} 条
              </span>
            </div>

            <!-- 风险提示 -->
            <a-alert
              v-if="!techRequirementsGenerated"
              type="info"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              message="请先在「评分点」Tab 中确认评分点，切换到「技术需求」Tab 点击生成，生成完成后再保存确认"
            />
            <a-alert
              v-else-if="unconfirmedHighRiskCount > 0"
              type="warning"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              :message="`还有 ${unconfirmedHighRiskCount} 条高分值（≥20分）评分点未确认`"
            />
            <a-alert
              v-else-if="confirmedCount === scorePoints.length && scorePoints.length > 0"
              type="success"
              :show-icon="true"
              class="parse-confirm__risk-alert"
              message="所有评分点已确认，可以生成大纲了"
            />
          </div>

          <div class="parse-confirm__footer-right">
            <!-- 第一步：保存确认（技术需求生成后才能点击） -->
            <a-tooltip :title="canSaveConfirm ? '保存当前所有评分点的确认状态和应对策略' : '请先生成技术需求，再保存确认'">
              <a-button
                :loading="savingAll"
                :disabled="!canSaveConfirm"
                @click="handleSaveAll"
              >
                <template #icon>
                  <SaveOutlined />
                </template>
                保存确认
              </a-button>
            </a-tooltip>

            <!-- 第二步：生成大纲 -->
            <a-tooltip :title="canGenerate ? '确认评分点并跳转到大纲生成页面' : '请先确认至少一条评分点'">
              <a-button
                type="primary"
                :loading="confirming"
                :disabled="!canGenerate"
                @click="handleConfirm"
              >
                <template #icon>
                  <ThunderboltOutlined />
                </template>
                生成大纲
              </a-button>
            </a-tooltip>
          </div>
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
import { SaveOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import {
  fetchScorePoints,
  updateScorePoint,
  fetchRequirements,
  generateRequirements,
  downloadProjectDocument,
  reparseDocument,
  fetchDocFormatRequirements,
  saveDocFormatRequirements,
  fetchDocDisqualificationClauses,
  saveDocDisqualificationClauses,
  fetchProjectDocuments,
  fetchWorkflowStatus,
  startWorkflow,
  confirmScorePoints,
} from '@/api'
import type { WorkflowStatus } from '@/types'
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


withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

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
const techRequirements = ref<TechRequirement[]>([])
const tenderDoc = ref<TenderDocItem | null>(null)
const reparseLoading = ref(false)
const selectedRowKeys = ref<string[]>([])
const generateLoading = ref(false)
const techRequirementsGenerated = ref(false)
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
const unconfirmedHighRiskCount = computed(() => scorePoints.value.filter((p) => !p.confirmed && (p.score ?? 0) >= 20).length)
const canGenerate = computed(() => confirmedCount.value > 0)
const canSaveConfirm = computed(() => techRequirementsGenerated.value)
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
    const res = await saveDocFormatRequirements(projectId, tenderDoc.value.id, items)
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
    const resp = await downloadProjectDocument(projectId, tenderDoc.value.id)
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
    const res = await saveDocDisqualificationClauses(
      projectId,
      tenderDoc.value.id,
      disqualificationClauses.value.map((it) => ({ id: it.id, clause_no: it.clause_no, title: it.title, risk_category: it.risk_category, severity: it.severity, recommendation: it.recommendation, confirmed: it.confirmed })),
    )
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
      fetchScorePoints(projectId),
      // 获取技术需求，只显示关联到评分点的
      fetchRequirements(projectId),
    ])
    scorePoints.value = spRes.data?.data || []
    const allRequirements = trRes.data?.data || []
    // 只保留关联到评分点的需求
    techRequirements.value = allRequirements.filter((r: TechRequirement) => r.related_sp != null)
    // 如果有关联的需求，说明已经生成过技术需求
    techRequirementsGenerated.value = techRequirements.value.length > 0
    const docRes = await fetchProjectDocuments(projectId, { doc_type: 'tender_file' })
    const docItems = docRes.data?.data?.items || []
    tenderDoc.value = docItems[0] || null
    if (tenderDoc.value) {
      const fmtRes = await fetchDocFormatRequirements(projectId, tenderDoc.value.id)
      const items = fmtRes.data?.data?.items || []
      formatRequirements.value = items.map((it: { category: string; requirement: string }, i: number) => ({ key: `fmt-${i}`, ...it }))
      try {
        const dqRes = await fetchDocDisqualificationClauses(projectId, tenderDoc.value.id)
        disqualificationClauses.value = dqRes.data?.data?.items || []
      } catch { disqualificationClauses.value = [] }
    }
  } catch { loadError.value = '解析数据加载失败' }
  finally { loading.value = false }
}

const handleGenerateRequirements = async () => {
  generateLoading.value = true
  try {
    // 必须根据已确认的评分点生成技术需求（持久化状态，而非临时行选择）
    const confirmedSpIds = scorePoints.value
      .filter((p) => p.confirmed)
      .map((p) => p.id)
    if (confirmedSpIds.length === 0) {
      message.warning('请先在评分点列表中确认需要生成技术需求的评分点')
      generateLoading.value = false
      return
    }
    const res = await generateRequirements(projectId, confirmedSpIds)
    if (res.data?.code !== 0) { message.error(res.data?.message || '技术需求生成失败'); return }
    const data = res.data?.data || { total: 0, mapped: 0 }
    message.success(`已生成 ${data.mapped} 条关联到评分点的技术需求`)
    // 获取技术需求，只显示关联到评分点的
    const trRes = await fetchRequirements(projectId)
    const allRequirements = trRes.data?.data || []
    techRequirements.value = allRequirements.filter((r: TechRequirement) => r.related_sp != null)
    techRequirementsGenerated.value = true
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '技术需求生成失败')
  } finally { generateLoading.value = false }
}

const handleReparse = async () => {
  if (!tenderDoc.value) return
  reparseLoading.value = true
  try {
    await reparseDocument(projectId, tenderDoc.value.id)
    message.success('已发起重新解析，页面即将刷新')
    window.location.reload()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '重新解析发起失败')
  } finally { reparseLoading.value = false }
}

/** 行内防抖自动保存（2026-08-25 B+C 优化）：1s 内合并同一行连续修改，静默落库 */
const handleAutoSave = (row: ScorePoint) => {
  const prev = autoSaveTimers.get(row.id)
  if (prev) clearTimeout(prev)
  autoSaveTimers.set(
    row.id,
    setTimeout(async () => {
      autoSaveTimers.delete(row.id)
      try {
        const res = await updateScorePoint(projectId, row.id, {
          strategy: row.strategy,
          confirmed: row.confirmed,
        })
        if (res.data?.code !== 0) {
          message.error(res.data?.message || '自动保存失败')
        }
      } catch {
        message.error('自动保存失败')
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
      await updateScorePoint(projectId, id, { strategy: row.strategy, confirmed: row.confirmed })
    } catch {
      message.error(`评分点自动保存失败（${row.item || id}）`)
    }
  }
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
      const res = await updateScorePoint(projectId, p.id, { confirmed: true })
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
      const res = await updateScorePoint(projectId, p.id, { strategy })
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
  const res = await fetchWorkflowStatus(projectId)
  return res.data?.data || null
}

const ensureScorePointInterrupt = async (): Promise<boolean> => {
  let status = await getWorkflowStatus()
  if (status?.interrupt?.type === 'confirm_score_points') return true
  if (status?.interrupt) { message.warning('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作'); return false }
  const phase = status?.phase || 'init'
  if (phase === 'init') { await startWorkflow(projectId) }
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

/** 保存确认 = 流程闸门（2026-08-25 B+C 优化：不再循环写库，评分点 Tab 已自动保存）.
 *
 * 校验顺序：先 flush 防抖队列强制落库（兜底）→ 全部评分点已确认 → 技术需求已生成。
 * 通过后由「确认并生成大纲」推进工作流，本按钮仅做就绪校验与引导。
 */
const handleSaveAll = async () => {
  if (scorePoints.value.length === 0) {
    message.info('暂无评分点需要保存')
    return
  }
  savingAll.value = true
  try {
    // 1. 强制落库防抖队列中尚未提交的修改（防用户 1s 内点击导致丢数据）
    await flushPendingSaves()
    // 2. 全部评分点已确认
    if (confirmedCount.value !== scorePoints.value.length) {
      message.warning(`还有 ${scorePoints.value.length - confirmedCount.value} 条评分点未确认`)
      return
    }
    // 3. 技术需求已生成（LLM 产物落库）
    if (!techRequirementsGenerated.value) {
      message.warning('请先切换到「技术需求」Tab 点击生成，再保存确认')
      return
    }
    message.success('评分点已全部确认，可以生成大纲')
  } finally {
    savingAll.value = false
  }
}

const handleConfirm = async () => {
  confirming.value = true
  const hideLoading = message.loading('正在启动解析工作流...', 0)
  try {
    // 推进工作流前强制落库防抖队列（评分点编辑即存，工作流从 DB 读最新状态）
    await flushPendingSaves()
    const ready = await ensureScorePointInterrupt()
    if (!ready) return
    hideLoading()
    await confirmScorePoints(projectId)
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

/* 固定底部操作栏 */
.parse-confirm__footer {
  position: sticky;
  bottom: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  margin-top: 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.08);
}

.parse-confirm__footer-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.parse-confirm__footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* 确认进度 */
.parse-confirm__progress {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.parse-confirm__progress-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.parse-confirm__progress-bar {
  width: 120px;
  flex-shrink: 0;
}

.parse-confirm__progress-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
}

/* 风险提示 */
.parse-confirm__risk-alert {
  flex: 1;
  min-width: 0;
}

.parse-confirm__risk-alert :deep(.ant-alert-message) {
  font-size: var(--font-size-sm);
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
