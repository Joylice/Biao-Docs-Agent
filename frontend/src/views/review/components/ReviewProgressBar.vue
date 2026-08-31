<template>
  <div class="review-progress">
    <div class="review-progress__stats">
      <div class="review-progress__item">
        <span class="review-progress__label">总章节</span>
        <span class="review-progress__value">{{ total }}</span>
      </div>
      <div class="review-progress__item review-progress__item--approved">
        <span class="review-progress__label">已通过</span>
        <span class="review-progress__value">{{ approved }}</span>
      </div>
      <div class="review-progress__item review-progress__item--rejected">
        <span class="review-progress__label">需修改</span>
        <span class="review-progress__value">{{ rejected }}</span>
      </div>
      <div class="review-progress__item review-progress__item--pending">
        <span class="review-progress__label">未审阅</span>
        <span class="review-progress__value">{{ pending }}</span>
      </div>
      <div class="review-progress__item review-progress__item--annotation">
        <span class="review-progress__label">有批注</span>
        <span class="review-progress__value">{{ annotated }}</span>
      </div>
    </div>
    <div class="review-progress__bar">
      <a-progress
        :percent="progressPercent"
        :stroke-color="{ from: '#52c41a', to: '#73d13d' }"
        :show-info="false"
        size="small"
      />
      <span class="review-progress__percent">{{ progressPercent }}% 已审阅</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  total: number
  approved: number
  rejected: number
  annotated: number
}>()

const pending = computed(() => props.total - props.approved - props.rejected)
const progressPercent = computed(() => {
  if (props.total === 0) return 0
  return Math.round(((props.approved + props.rejected) / props.total) * 100)
})
</script>

<style scoped>
.review-progress {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 12px 20px;
  background: var(--bg-elevated, #1f1f1f);
  border: 1px solid var(--border-color, #303030);
  border-radius: 8px;
  margin-bottom: 16px;
}

.review-progress__stats {
  display: flex;
  gap: 20px;
  flex-shrink: 0;
}

.review-progress__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.review-progress__label {
  font-size: 11px;
  color: var(--text-secondary, #999);
}

.review-progress__value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.review-progress__item--approved .review-progress__value {
  color: #52c41a;
}

.review-progress__item--rejected .review-progress__value {
  color: #fa8c16;
}

.review-progress__item--pending .review-progress__value {
  color: var(--text-secondary, #999);
}

.review-progress__item--annotation .review-progress__value {
  color: #1890ff;
}

.review-progress__bar {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.review-progress__percent {
  font-size: 12px;
  color: var(--text-secondary, #999);
  flex-shrink: 0;
  min-width: 60px;
  text-align: right;
}
</style>
