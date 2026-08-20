<template>
  <a-card title="评分点">
    <template #extra>
      <a-space>
        <a-button size="small" @click="$emit('open-batch-strategy')">批量修改策略</a-button>
        <a-button size="small" :loading="confirmAllLoading" @click="$emit('confirm-all')">一键全确认</a-button>
        <a-button v-if="tenderDoc" size="small" :loading="downloadTenderLoading" @click="$emit('download-tender')">
          下载招标文件
        </a-button>
        <a-popconfirm
          v-if="canReparse"
          title="重新解析将清除现有评分点与衍生技术需求，确认继续？"
          ok-text="重新解析"
          cancel-text="取消"
          @confirm="$emit('reparse')"
        >
          <a-button size="small" :loading="reparseLoading">重新解析</a-button>
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
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'score'">
          <span class="parse-score" :class="{ 'parse-score--high': isHighScore(record.score) }">
            {{ record.score ?? '-' }}
          </span>
        </template>
        <template v-if="column.key === 'is_star'">
          <a-tag :color="record.is_star ? 'red' : 'default'">
            {{ record.is_star ? '★ 重点' : '普通' }}
          </a-tag>
        </template>
        <template v-if="column.key === 'risk_level'">
          <a-tag :color="riskColor(record.risk_level)">{{ record.risk_level || '-' }}</a-tag>
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
          <a-button size="small" type="link" :loading="savingId === record.id" @click="$emit('save-row', record)">
            保存
          </a-button>
        </template>
      </template>
    </a-table>
  </a-card>
</template>

<script setup lang="ts">
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

defineProps<{
  scorePoints: ScorePoint[]
  selectedRowKeys: string[]
  savingId: string
  confirmAllLoading: boolean
  reparseLoading: boolean
  downloadTenderLoading: boolean
  tenderDoc: TenderDocItem | null
  canReparse: boolean
}>()

const emit = defineEmits<{
  (e: 'update:selectedRowKeys', keys: string[]): void
  (e: 'save-row', record: ScorePoint): void
  (e: 'confirm-all'): void
  (e: 'open-batch-strategy'): void
  (e: 'reparse'): void
  (e: 'download-tender'): void
}>()

const isHighScore = (score: number | null): boolean => (score ?? 0) >= 20
const scoreRowClassName = (record: ScorePoint): string => (isHighScore(record.score) ? 'parse-row--high' : '')

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

const riskColor = (level: string | null) => {
  const colors: Record<string, string> = { high: 'red', mid: 'orange', low: 'green' }
  return colors[level || ''] || 'default'
}

const onSelectionChange = (keys: string[] | number[]) => {
  emit('update:selectedRowKeys', keys.map(String))
}
</script>

<style scoped>
.parse-score { font-weight: 600; }
.parse-score--high { color: var(--color-error); font-weight: 700; }
.parse-row--high td { background: var(--color-error-bg) !important; }
</style>
