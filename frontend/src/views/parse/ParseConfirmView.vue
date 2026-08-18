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
        <!-- 确认进度 + 分值统计 -->
        <a-card
          :bordered="false"
          class="summary-card mb-4"
        >
          <a-row :gutter="[16, 16]">
            <a-col
              :xs="24"
              :sm="8"
            >
              <div class="summary-item">
                <div class="summary-item__label">
                  确认进度
                </div>
                <a-progress
                  :percent="confirmedPercent"
                  size="small"
                  :status="confirmedPercent === 100 ? 'success' : 'active'"
                />
                <div class="summary-item__hint">
                  已确认 {{ confirmedCount }} / {{ scorePoints.length }} 条
                </div>
              </div>
            </a-col>
            <a-col
              :xs="12"
              :sm="8"
            >
              <div class="summary-item">
                <div class="summary-item__label">
                  分值合计
                </div>
                <div class="summary-item__value">
                  {{ totalScore }}
                  <span class="summary-item__unit">分</span>
                </div>
              </div>
            </a-col>
            <a-col
              :xs="12"
              :sm="8"
            >
              <div class="summary-item">
                <div class="summary-item__label">
                  高分值风险项
                </div>
                <div class="summary-item__value summary-item__value--danger">
                  {{ highRiskCount }}
                  <span class="summary-item__unit">条（≥ 20 分）</span>
                </div>
              </div>
            </a-col>
          </a-row>
        </a-card>

        <!-- 格式要求汇总（LLM 提取 + 人工可编辑，驱动 Word 导出排版） -->
        <a-card
          v-if="tenderDoc"
          title="格式要求汇总"
          class="mb-4"
        >
          <template #extra>
            <a-space>
              <a-button
                size="small"
                @click="handleAddFormatItem"
              >
                新增条目
              </a-button>
              <a-button
                size="small"
                type="primary"
                :loading="formatSaving"
                @click="handleSaveFormat"
              >
                保存
              </a-button>
            </a-space>
          </template>
          <a-alert
            v-if="formatRequirements.length === 0"
            type="info"
            show-icon
            message="未提取到格式要求，可手动新增（字体字号、行距、页边距等将应用到 Word 导出排版）"
          />
          <div
            v-else
            class="format-list"
          >
            <div
              v-for="group in formatGroups"
              :key="group.category"
              class="format-group"
            >
              <div class="format-group__label">
                {{ formatCategoryLabel(group.category) }}
              </div>
              <div
                v-for="item in group.items"
                :key="item.key"
                class="format-item"
              >
                <a-select
                  v-model:value="item.category"
                  :options="formatCategoryOptions"
                  style="width: 140px"
                  size="small"
                />
                <a-input
                  v-model:value="item.requirement"
                  size="small"
                  placeholder="格式要求描述，如：正文小四号仿宋、1.5 倍行距"
                />
                <a-button
                  size="small"
                  type="text"
                  danger
                  @click="handleRemoveFormatItem(item)"
                >
                  删除
                </a-button>
              </div>
            </div>
          </div>
        </a-card>

        <!-- 评分点表格 -->
        <a-card
          title="评分点"
          class="mb-4"
        >
          <template #extra>
            <a-space>
              <a-button
                size="small"
                @click="batchStrategyOpen = true"
              >
                批量修改策略
              </a-button>
              <a-button
                size="small"
                type="primary"
                :loading="confirmAllLoading"
                @click="handleConfirmAll"
              >
                一键全确认
              </a-button>
              <a-popconfirm
                v-if="canReparse"
                title="重新解析将清除现有评分点与衍生技术需求（招标原文需求保留），确认继续？"
                ok-text="重新解析"
                cancel-text="取消"
                @confirm="handleReparse"
              >
                <a-button
                  size="small"
                  :loading="reparseLoading"
                >
                  重新解析
                </a-button>
              </a-popconfirm>
            </a-space>
          </template>
          <a-table
            :columns="scoreColumns"
            :data-source="scorePoints"
            :pagination="{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }"
            :row-class-name="scoreRowClassName"
            :row-selection="{ selectedRowKeys, onChange: onSelectionChange }"
            :scroll="{ x: 1100 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'score'">
                <span
                  class="sp-score"
                  :class="{ 'sp-score--high': isHighScore(record.score) }"
                >
                  {{ record.score ?? '-' }}
                </span>
              </template>
              <template v-if="column.key === 'is_star'">
                <a-tag :color="record.is_star ? 'red' : 'default'">
                  {{ record.is_star ? '★ 重点' : '普通' }}
                </a-tag>
              </template>
              <template v-if="column.key === 'risk_level'">
                <a-tag :color="riskColor(record.risk_level)">
                  {{ record.risk_level || '-' }}
                </a-tag>
              </template>
              <template v-if="column.key === 'confirmed'">
                <a-checkbox v-model:checked="record.confirmed" />
              </template>
              <template v-if="column.key === 'strategy'">
                <a-input
                  v-model:value="record.strategy"
                  placeholder="填写应对策略..."
                  type="textarea"
                  :rows="2"
                />
              </template>
              <template v-if="column.key === 'action'">
                <a-button
                  size="small"
                  type="link"
                  :loading="savingId === record.id"
                  @click="handleSaveRow(record)"
                >
                  保存
                </a-button>
              </template>
            </template>
          </a-table>
        </a-card>

        <!-- 技术需求 -->
        <a-card
          title="技术需求"
          class="mb-4"
        >
          <template #extra>
            <a-popconfirm
              title="将基于评分点重新梳理衍生需求（已有衍生需求会被重建），确认继续？"
              ok-text="生成"
              cancel-text="取消"
              @confirm="handleGenerateRequirements"
            >
              <a-button
                size="small"
                type="primary"
                :loading="generateLoading"
              >
                {{ selectedRowKeys.length > 0 ? `生成技术需求（已选 ${selectedRowKeys.length} 项）` : '生成技术需求（全部已确认）' }}
              </a-button>
            </a-popconfirm>
          </template>
          <a-table
            :columns="techColumns"
            :data-source="techRequirements"
            :pagination="false"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'is_mandatory'">
                <a-tag :color="record.is_mandatory ? 'red' : 'blue'">
                  {{ record.is_mandatory ? '强制' : '建议' }}
                </a-tag>
              </template>
              <template v-if="column.key === 'source'">
                <a-tag :color="record.source === 'sp_derived' ? 'green' : 'default'">
                  {{ record.source === 'sp_derived' ? '评分点衍生' : '招标原文' }}
                </a-tag>
              </template>
              <template v-if="column.key === 'related_sp'">
                <span v-if="record.related_sp">
                  {{ record.related_sp.clause_no }} {{ record.related_sp.item }}
                </span>
                <span v-else>—</span>
              </template>
            </template>
          </a-table>
        </a-card>

        <!-- 操作按钮 -->
        <div class="actions">
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
        placeholder="输入统一的应对策略模板，将应用到所有评分点（可后续逐条微调）"
      />
    </a-modal>
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

interface TenderDocItem {
  id: string
  title: string
  status: string
}

interface TechRequirement {
  id: string
  seq: number
  description: string
  category: string | null
  is_mandatory: boolean
  sp_id?: string | null
  source?: string | null
  related_sp?: { clause_no: string; item: string } | null
}

/** 内嵌模式：由解析入口页（ParseView）在已有解析数据时渲染，不重复展示标题 */
withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  {
    embedded: false,
  },
)

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

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
let formatKeySeq = 0

/** 按分类分组展示（保持后端分类枚举顺序） */
const formatGroups = computed(() => {
  const groups: { category: string; items: FormatRequirementItem[] }[] = []
  for (const cat of FORMAT_CATEGORIES.map((c) => c.value)) {
    const items = formatRequirements.value.filter((it) => it.category === cat)
    if (items.length > 0) groups.push({ category: cat, items })
  }
  // 未知分类归入末尾
  const known = new Set(FORMAT_CATEGORIES.map((c) => c.value))
  const unknown = formatRequirements.value.filter((it) => !known.has(it.category))
  if (unknown.length > 0) groups.push({ category: 'other', items: unknown })
  return groups
})

const handleAddFormatItem = () => {
  formatKeySeq += 1
  formatRequirements.value.push({ key: `new-${formatKeySeq}`, category: 'other', requirement: '' })
}

const handleRemoveFormatItem = (item: FormatRequirementItem) => {
  formatRequirements.value = formatRequirements.value.filter((it) => it.key !== item.key)
}

/** 保存格式要求：清洗空条目后幂等覆盖（PUT 完整数组） */
const handleSaveFormat = async () => {
  if (!tenderDoc.value) return
  const items = formatRequirements.value
    .map((it) => ({ category: it.category, requirement: it.requirement.trim() }))
    .filter((it) => it.requirement)
  formatSaving.value = true
  try {
    const res = await api.put(
      `/projects/${projectId}/documents/${tenderDoc.value.id}/format-requirements`,
      { format_requirements: items },
    )
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '格式要求保存失败')
      return
    }
    const saved = res.data?.data?.items || []
    formatRequirements.value = saved.map(
      (it: { category: string; requirement: string }, i: number) => ({
        key: `fmt-${i}`,
        category: it.category,
        requirement: it.requirement,
      }),
    )
    message.success(`格式要求已保存（${saved.length} 条），导出 Word 时将应用该排版`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '格式要求保存失败')
  } finally {
    formatSaving.value = false
  }
}

/** 重新解析入口可用：内嵌模式且最新招标文件已完成解析或解析失败 */
const canReparse = computed(
  () => !!tenderDoc.value && ['parsed', 'failed'].includes(tenderDoc.value.status),
)

const confirmedCount = computed(() => scorePoints.value.filter((p) => p.confirmed).length)
const confirmedPercent = computed(() =>
  scorePoints.value.length === 0 ? 0 : Math.round((confirmedCount.value / scorePoints.value.length) * 100),
)
const totalScore = computed(() =>
  scorePoints.value.reduce((sum, p) => sum + (p.score ?? 0), 0),
)
const highRiskCount = computed(() => scorePoints.value.filter((p) => isHighScore(p.score)).length)

const isHighScore = (score: number | null): boolean => (score ?? 0) >= 20

const scoreRowClassName = (record: ScorePoint): string => {
  return isHighScore(record.score) ? 'sp-row--high' : ''
}

const scoreColumns = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 100 },
  { title: '评分项', dataIndex: 'item', key: 'item' },
  { title: '分值', dataIndex: 'score', key: 'score', width: 90, sorter: (a: ScorePoint, b: ScorePoint) => (a.score ?? 0) - (b.score ?? 0) },
  { title: '评分标准', dataIndex: 'criteria', key: 'criteria', ellipsis: { showTitle: true } },
  { title: '要求级别', key: 'is_star', width: 90 },
  { title: '风险', key: 'risk_level', width: 80 },
  { title: '确认', key: 'confirmed', width: 60 },
  { title: '应对策略', key: 'strategy', width: 200 },
  { title: '操作', key: 'action', width: 70, fixed: 'right' as const },
]

const techColumns = [
  { title: '序号', dataIndex: 'seq', key: 'seq', width: 60 },
  { title: '需求描述', dataIndex: 'description', key: 'description' },
  { title: '分类', dataIndex: 'category', key: 'category', width: 100 },
  { title: '类型', key: 'is_mandatory', width: 80 },
  { title: '来源', key: 'source', width: 110 },
  { title: '对应评分点', key: 'related_sp', width: 240 },
]

const riskColor = (level: string | null) => {
  const colors: Record<string, string> = { high: 'red', mid: 'orange', low: 'green' }
  return colors[level || ''] || 'default'
}

interface FormatRequirementItem {
  key: string
  category: string
  requirement: string
}

/** 格式要求分类枚举（与后端 parse.yaml / format_spec 对齐） */
const FORMAT_CATEGORIES: { value: string; label: string }[] = [
  { value: 'font_body', label: '正文字体字号' },
  { value: 'font_heading', label: '标题字体字号' },
  { value: 'line_spacing', label: '行距' },
  { value: 'margin', label: '页边距' },
  { value: 'page_setup', label: '页面设置' },
  { value: 'binding', label: '装订' },
  { value: 'page_number', label: '页码' },
  { value: 'toc', label: '目录' },
  { value: 'other', label: '其他' },
]

const formatCategoryOptions = FORMAT_CATEGORIES
const formatCategoryLabel = (value: string) =>
  FORMAT_CATEGORIES.find((c) => c.value === value)?.label || value

const fetchData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [spRes, trRes] = await Promise.all([
      api.get(`/projects/${projectId}/score-points`),
      // 确认页只展示与评分点关联的需求；招标原文提取的无映射需求不参与评分点确认
      api.get(`/projects/${projectId}/requirements`, { params: { only_mapped: true } }),
    ])
    scorePoints.value = spRes.data?.data || []
    techRequirements.value = trRes.data?.data || []
    // 招标文件列表（重新解析入口需要 doc id；列表接口按创建时间倒序，取最新一份）
    const docRes = await api.get(`/projects/${projectId}/documents`, {
      params: { doc_type: 'tender_file' },
    })
    const docItems = docRes.data?.data?.items || docRes.data?.data || []
    tenderDoc.value = docItems[0] || null
    // 格式要求汇总（依赖最新招标文件 doc_id）
    if (tenderDoc.value) {
      const fmtRes = await api.get(
        `/projects/${projectId}/documents/${tenderDoc.value.id}/format-requirements`,
      )
      const items = fmtRes.data?.data?.items || []
      formatRequirements.value = items.map((it: { category: string; requirement: string }, i: number) => ({
        key: `fmt-${i}`,
        category: it.category,
        requirement: it.requirement,
      }))
    }
  } catch {
    loadError.value = '解析数据加载失败'
  } finally {
    loading.value = false
  }
}

/** 技术需求梳理：勾选评分点 → 按勾选梳理；未勾选 → 全部已确认评分点 */
const onSelectionChange = (keys: string[] | number[]) => {
  selectedRowKeys.value = keys.map(String)
}

const handleGenerateRequirements = async () => {
  generateLoading.value = true
  try {
    const body = selectedRowKeys.value.length > 0
      ? { score_point_ids: selectedRowKeys.value }
      : {}
    const res = await api.post(`/projects/${projectId}/requirements/generate`, body)
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '技术需求生成失败')
      return
    }
    const data = res.data?.data || {}
    message.success(`已生成 ${data.total} 条需求，其中 ${data.mapped} 条关联到评分点`)
    // 刷新技术需求列表（含映射关系，仅展示已映射）
    const trRes = await api.get(`/projects/${projectId}/requirements`, { params: { only_mapped: true } })
    techRequirements.value = trRes.data?.data || []
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '技术需求生成失败')
  } finally {
    generateLoading.value = false
  }
}

/** 重新解析：清除旧解析结果 → 重新入队 → 刷新回文件列表态等待解析完成 */
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
  } finally {
    reparseLoading.value = false
  }
}

/** 逐条保存（strategy / confirmed 走 PUT /score-points/{id}） */
const handleSaveRow = async (row: ScorePoint) => {
  savingId.value = row.id
  try {
    const res = await api.put(`/projects/${projectId}/score-points/${row.id}`, {
      strategy: row.strategy,
      confirmed: row.confirmed,
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '保存失败')
      return
    }
    message.success('已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingId.value = ''
  }
}

/** 一键全确认：逐条提交 confirmed=true */
const handleConfirmAll = async () => {
  const pending = scorePoints.value.filter((p) => !p.confirmed)
  if (pending.length === 0) {
    message.info('评分点已全部确认')
    return
  }
  confirmAllLoading.value = true
  try {
    for (const p of pending) {
      const res = await api.put(`/projects/${projectId}/score-points/${p.id}`, { confirmed: true })
      if (res.data?.code !== 0) {
        message.error(res.data?.message || '确认失败')
        return
      }
      p.confirmed = true
    }
    message.success(`已确认 ${pending.length} 条评分点`)
  } catch {
    message.error('批量确认失败，请重试')
  } finally {
    confirmAllLoading.value = false
  }
}

/** 批量修改 strategy：统一文案应用到全部评分点 */
const handleApplyBatchStrategy = async () => {
  const strategy = batchStrategy.value.trim()
  if (!strategy) {
    message.warning('请输入策略内容')
    return
  }
  batchStrategyLoading.value = true
  try {
    for (const p of scorePoints.value) {
      const res = await api.put(`/projects/${projectId}/score-points/${p.id}`, { strategy })
      if (res.data?.code !== 0) {
        message.error(res.data?.message || '应用失败')
        return
      }
      p.strategy = strategy
    }
    message.success(`已应用到全部 ${scorePoints.value.length} 条评分点`)
    batchStrategyOpen.value = false
  } catch {
    message.error('批量修改失败，请重试')
  } finally {
    batchStrategyLoading.value = false
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface WorkflowStatus {
  phase: string
  error: string
  interrupt: { type: string } | null
}

const getWorkflowStatus = async (): Promise<WorkflowStatus | null> => {
  const res = await api.get(`/projects/${projectId}/workflow/status`)
  return res.data?.data || null
}

/**
 * 确保工作流停在评分点 interrupt：未启动则先 start，再轮询等待解析节点完成。
 * 后端 confirm-score-points 校验 pending interrupt，未启动直接确认会 4009。
 */
const ensureScorePointInterrupt = async (): Promise<boolean> => {
  let status = await getWorkflowStatus()
  if (status?.interrupt?.type === 'confirm_score_points') return true
  // 已挂起其他类型 interrupt（大纲确认/章节审阅）：工作流已推进到后续阶段，
  // 直接引导去方案生成页，避免盲目轮询空转（此前会一直转圈到 60s 超时）
  if (status?.interrupt) {
    message.warning('工作流已进入后续阶段，请前往「方案生成」页继续操作')
    return false
  }
  // 无 interrupt：phase=init 才启动；phase=confirm 时 parse 节点刚完成、
  // interrupt 即将挂起，轮询等待即可（在途重复 start 会被后端 4009 拒绝）
  const phase = status?.phase || 'init'
  if (phase === 'init') {
    await api.post(`/projects/${projectId}/workflow/start`)
  } else if (phase !== 'confirm') {
    message.warning('工作流已进入后续阶段，请前往「方案生成」页继续操作')
    return false
  }
  // 轮询等待 interrupt 就绪（parse 节点后台异步执行；error 提前终止）
  for (let i = 0; i < 60; i += 1) {
    await sleep(1000)
    status = await getWorkflowStatus()
    if (status?.interrupt?.type === 'confirm_score_points') return true
    // 轮询期间进入其他阶段（如大纲确认/审阅）：停止等待并引导
    if (status?.interrupt) {
      message.warning('工作流已进入后续阶段，请前往「方案生成」页继续操作')
      return false
    }
    if (status?.error) {
      message.error(`解析失败：${status.error}`)
      return false
    }
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
  } finally {
    hideLoading()
    confirming.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.parse-confirm { max-width: 1200px; }
.mb-4 { margin-bottom: 16px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }

.summary-card {
  background: var(--card-bg);
}

.summary-item__label {
  font-size: 13px;
  color: var(--text-secondary, #666);
  margin-bottom: 6px;
}

.summary-item__value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary, #222);
}

.summary-item__value--danger {
  color: #c62828;
}

.summary-item__unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary, #999);
}

.summary-item__hint {
  font-size: 12px;
  color: var(--text-secondary, #999);
  margin-top: 4px;
}

.sp-score {
  font-weight: 600;
}

.sp-score--high {
  color: #c62828;
  font-weight: 700;
}

.sp-row--high td {
  background: rgba(198, 40, 40, 0.05) !important;
}

.format-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.format-group__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #666);
  margin-bottom: 6px;
}

.format-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
</style>
