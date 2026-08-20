<template>
  <a-card
    :bordered="false"
    class="parse-summary"
  >
    <a-row :gutter="[16, 16]">
      <a-col
        :xs="24"
        :sm="8"
      >
        <div class="parse-summary__item">
          <div class="parse-summary__label">
            确认进度
          </div>
          <a-progress
            :percent="confirmedPercent"
            size="small"
            :status="confirmedPercent === 100 ? 'success' : 'active'"
          />
          <div class="parse-summary__hint">
            已确认 {{ confirmedCount }} / {{ total }} 条
          </div>
        </div>
      </a-col>
      <a-col
        :xs="12"
        :sm="8"
      >
        <div class="parse-summary__item">
          <div class="parse-summary__label">
            分值合计
          </div>
          <div class="parse-summary__value">
            {{ totalScore }}
            <span class="parse-summary__unit">分</span>
          </div>
        </div>
      </a-col>
      <a-col
        :xs="12"
        :sm="8"
      >
        <div class="parse-summary__item">
          <div class="parse-summary__label">
            高分值风险项
          </div>
          <div class="parse-summary__value parse-summary__value--danger">
            {{ highRiskCount }}
            <span class="parse-summary__unit">条（≥ 20 分）</span>
          </div>
        </div>
      </a-col>
    </a-row>
  </a-card>
</template>

<script setup lang="ts">
defineProps<{
  confirmedPercent: number
  confirmedCount: number
  total: number
  totalScore: number
  highRiskCount: number
}>()
</script>

<style scoped>
.parse-summary {
  background: var(--bg-surface);
}

.parse-summary__item {
  padding: 4px 0;
}

.parse-summary__label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.parse-summary__value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.parse-summary__value--danger {
  color: var(--color-error);
}

.parse-summary__unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-tertiary);
}

.parse-summary__hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}
</style>
