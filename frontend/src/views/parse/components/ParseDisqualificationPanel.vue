<template>
  <a-card title="废标风险">
    <a-alert
      v-if="clauses.length === 0"
      type="info"
      show-icon
      message="未提取到废标条款"
    />

    <template v-else>
      <a-alert
        type="error"
        show-icon
        message="以下条款违反将直接导致废标，请逐条人工确认"
        class="parse-dq__alert"
      />
      <div class="parse-dq__list">
        <div
          v-for="clause in clauses"
          :key="clause.id"
          class="parse-dq__item"
        >
          <div class="parse-dq__main">
            <div class="parse-dq__title">
              {{ clause.clause_no }} {{ clause.title }}
              <a-tag class="parse-dq__category">
                {{ RISK_CATEGORY_LABELS[clause.risk_category] || clause.risk_category }}
              </a-tag>
              <a-tag :color="SEVERITY_META[clause.severity]?.color ?? 'default'">
                {{ SEVERITY_META[clause.severity]?.text ?? clause.severity }}
              </a-tag>
            </div>
            <div
              v-if="clause.recommendation"
              class="parse-dq__recommendation"
            >
              {{ clause.recommendation }}
            </div>
          </div>
          <a-checkbox
            :checked="clause.confirmed"
            :disabled="saving"
            @change="onChecked(clause, $event)"
          >
            已确认
          </a-checkbox>
        </div>
      </div>
    </template>
  </a-card>
</template>

<script setup lang="ts">
interface DisqualificationClause {
  id: string
  clause_no: string
  title: string
  risk_category: string
  severity: string
  recommendation: string
  confirmed: boolean
}

defineProps<{
  clauses: DisqualificationClause[]
  saving: boolean
}>()

const emit = defineEmits<{
  (e: 'checked', clause: DisqualificationClause, checked: boolean): void
}>()

const onChecked = (clause: DisqualificationClause, e: any) => {
  const checked = (e.target as HTMLInputElement).checked
  emit('checked', clause, checked)
}

const RISK_CATEGORY_LABELS: Record<string, string> = {
  qualification_missing: '资质缺失',
  schedule_exceeded: '工期超限',
  signature_seal: '签章要求',
  blind_bid: '暗标规则',
  format_deviation: '格式偏离',
  substantive_deviation: '实质性偏离',
  other: '其他',
}

const SEVERITY_META: Record<string, { text: string; color: string }> = {
  high: { text: '高', color: 'error' },
  mid: { text: '中', color: 'warning' },
  low: { text: '低', color: 'default' },
}
</script>

<style scoped>
.parse-dq__alert { margin-bottom: 12px; }

.parse-dq__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.parse-dq__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}

.parse-dq__main { min-width: 0; flex: 1; }

.parse-dq__title {
  font-weight: 600;
  color: var(--text-primary);
}

.parse-dq__category { margin-left: 8px; }

.parse-dq__recommendation {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
