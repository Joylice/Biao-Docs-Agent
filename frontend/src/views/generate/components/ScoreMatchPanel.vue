<template>
  <div class="score-match-panel">
    <div class="score-match-panel__header">
      <span class="score-match-panel__title">评分对标</span>
      <a-tag v-if="!loading && !error" color="blue">共 {{ items.length }} 项</a-tag>
      <a-button v-if="error" size="small" @click="$emit('retry')">重试</a-button>
    </div>

    <a-alert v-if="error" type="warning" show-icon :message="error" class="mb-4" />
    <LoadingSkeleton v-else-if="loading" :rows="5" />
    <a-empty v-else-if="items.length === 0" description="暂无评分点" />

    <a-table
      v-else
      :columns="columns"
      :data-source="items"
      :pagination="false"
      :scroll="{ x: 900 }"
      row-key="clause_no"
      size="small"
      class="score-match-panel__table"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'coverage'">
          <a-progress :percent="Math.round((record.coverage ?? 0) * 100)" size="small" />
        </template>
        <template v-else-if="column.key === 'risk'">
          <a-tag :color="riskMeta[record.risk as RiskLevel]?.color ?? 'default'">
            {{ riskMeta[record.risk as RiskLevel]?.text ?? '-' }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'strategy'">
          <span class="score-match-panel__strategy">{{ record.strategy || '—' }}</span>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import type { BenchmarkItem, RiskLevel } from '@/types'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

defineProps<{
  items: BenchmarkItem[]
  loading: boolean
  error: string
}>()

defineEmits<{
  (e: 'retry'): void
}>()

const riskMeta: Record<RiskLevel, { text: string; color: string }> = {
  high: { text: '高', color: 'red' },
  mid: { text: '中', color: 'orange' },
  low: { text: '低', color: 'default' },
}

const columns = [
  { title: '条款号', dataIndex: 'clause_no', key: 'clause_no', width: 80 },
  { title: '评分项', dataIndex: 'item', key: 'item', width: 140 },
  { title: '分值', dataIndex: 'score', key: 'score', width: 60 },
  { title: '覆盖度', key: 'coverage', width: 120 },
  { title: '风险', key: 'risk', width: 60 },
  { title: '应对策略', key: 'strategy', ellipsis: true },
]
</script>

<style scoped>
.score-match-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.score-match-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.score-match-panel__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.score-match-panel__table {
  margin-top: 8px;
}

.score-match-panel__strategy {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.mb-4 {
  margin-bottom: 16px;
}
</style>
