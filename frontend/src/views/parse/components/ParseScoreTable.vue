<template>
  <a-card title="评分点">
    <template #extra>
      <a-space>
        <a-button
          size="small"
          @click="$emit('open-batch-strategy')"
        >
          批量修改策略
        </a-button>
        <a-button
          v-if="tenderDoc"
          size="small"
          :loading="downloadTenderLoading"
          @click="$emit('download-tender')"
        >
          下载招标文件
        </a-button>
        <a-popconfirm
          v-if="canReparse"
          title="重新解析将清除现有评分点与衍生技术需求，确认继续？"
          ok-text="重新解析"
          cancel-text="取消"
          @confirm="$emit('reparse')"
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

    <!-- P2-1 虚拟滚动：行数 >100 时传 :virtual="true" + :scroll="{ y: 480, x: 1100 }"（列宽合计 1100）。
         实测核实（2026-08）：npmjs / npmmirror 双源 ant-design-vue 4.x 已发布最高版本为 4.2.6，
         其 Table 尚无 virtual 实现（随 ≥4.3 引入，暂未发布）。该绑定为前向兼容：4.2.6 下被忽略，
         升级至含 virtual 的版本后自动生效；≤100 行保持现状。 -->
    <a-table
      aria-label="评分点列表"
      :columns="scoreColumns"
      :data-source="scorePoints"
      :pagination="{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }"
      :row-class-name="scoreRowClassName"
      :row-selection="{ selectedRowKeys, onChange: onSelectionChange }"
      :virtual="useVirtual"
      :scroll="useVirtual ? { y: 480, x: 1030 } : { x: 1030 }"
      row-key="id"
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'score'">
          <span
            class="parse-score"
            :class="{ 'parse-score--high': isHighScore(record.score) }"
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
          <a-checkbox
            v-model:checked="record.confirmed"
            @change="() => emit('auto-save', record as ScorePoint)"
          />
        </template>
        <template v-if="column.key === 'strategy'">
          <a-textarea
            v-model:value="record.strategy"
            placeholder="填写应对策略..."
            :rows="2"
            @change="() => emit('auto-save', record as ScorePoint)"
          />
        </template>
      </template>
    </a-table>
  </a-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

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

const props = defineProps<{
  scorePoints: ScorePoint[]
  selectedRowKeys: string[]
  reparseLoading: boolean
  downloadTenderLoading: boolean
  tenderDoc: TenderDocItem | null
  canReparse: boolean
}>()

const emit = defineEmits<{
  (e: 'update:selectedRowKeys', keys: string[]): void
  (e: 'auto-save', record: ScorePoint): void
  (e: 'open-batch-strategy'): void
  (e: 'reparse'): void
  (e: 'download-tender'): void
}>()

/** 行数 >100 时启用虚拟滚动开关（ant-design-vue Table :virtual，随支持版本自动生效） */
const useVirtual = computed(() => props.scorePoints.length > 100)

const isHighScore = (score: number | null): boolean => (score ?? 0) >= 20
const scoreRowClassName = (record: ScorePoint): string => (isHighScore(record.score) ? 'parse-row--high' : '')

// 列宽合计 1030（scroll.x）：窄屏横向滚动 + 评分项列固定左侧
const scoreColumns = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 100 },
  { title: '评分项', dataIndex: 'item', key: 'item', width: 160, fixed: 'left' as const },
  { title: '分值', dataIndex: 'score', key: 'score', width: 90, sorter: (a: ScorePoint, b: ScorePoint) => (a.score ?? 0) - (b.score ?? 0) },
  { title: '评分标准', dataIndex: 'criteria', key: 'criteria', width: 250, ellipsis: { showTitle: true } },
  { title: '要求级别', key: 'is_star', width: 90 },
  { title: '风险', key: 'risk_level', width: 80 },
  { title: '确认', key: 'confirmed', width: 60 },
  { title: '应对策略', key: 'strategy', width: 200 },
]

const riskColor = (level: string | null) => {
  const colors: Record<string, string> = { high: 'red', mid: 'orange', low: 'green' }
  return colors[level || ''] || 'default'
}

const onSelectionChange = (keys: string[] | number[] | readonly (string | number)[]) => {
  emit('update:selectedRowKeys', Array.from(keys, String))
}
</script>

<style scoped>
.parse-score { font-weight: 600; }
.parse-score--high { color: var(--color-error); font-weight: 700; }
.parse-row--high td { background: var(--color-error-light) !important; }
</style>
