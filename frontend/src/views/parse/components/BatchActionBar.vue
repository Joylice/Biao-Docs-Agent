<template>
  <div class="batch-action-bar">
    <span class="batch-action-bar__count">
      已选 <strong class="batch-action-bar__num">{{ count }}</strong> 项
    </span>
    <a-button
      type="primary"
      :loading="loading"
      :class="{ 'batch-action-bar__confirm--success': success }"
      @click="$emit('confirm')"
    >
      <template #icon>
        <CheckOutlined v-if="success" />
      </template>
      {{ success ? '已确认' : '批量确认' }}
    </a-button>
    <a-button @click="$emit('clear')">
      取消勾选
    </a-button>
  </div>
</template>

<script setup lang="ts">
import { CheckOutlined } from '@ant-design/icons-vue'

/** 批量操作浮动栏：选中表格行后浮现，承载批量确认/取消勾选 */
withDefaults(
  defineProps<{
    /** 已选条目数 */
    count: number
    /** 批量确认进行中 */
    loading?: boolean
    /** 批量确认刚成功：短暂展示 success 样式 + 勾选图标 */
    success?: boolean
  }>(),
  {
    loading: false,
    success: false,
  },
)

defineEmits<{
  (e: 'confirm'): void
  (e: 'clear'): void
}>()
</script>

<style scoped>
.batch-action-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 16px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.batch-action-bar__count {
  font-size: var(--font-size-base);
  color: var(--text-secondary);
  white-space: nowrap;
}

.batch-action-bar__num {
  color: var(--color-primary);
  font-weight: 600;
}

/* 批量确认成功短暂反馈：success 底色（双主题走 CSS 变量） */
.batch-action-bar__confirm--success {
  background: var(--color-success);
  border-color: var(--color-success);
  color: var(--text-inverse);
}
</style>
