<template>
  <div class="error-state">
    <a-result
      status="warning"
      :title="description"
    >
      <template #icon>
        <WarningOutlined class="error-state__icon" />
      </template>
      <template
        v-if="$slots.action"
        #extra
      >
        <slot name="action" />
      </template>
    </a-result>
  </div>
</template>

<script setup lang="ts">
import { WarningOutlined } from '@ant-design/icons-vue'

withDefaults(defineProps<{ description?: string }>(), {
  description: '加载失败，请稍后重试',
})
</script>

<style scoped>
.error-state {
  padding: 32px 16px;
}

.error-state__icon {
  color: var(--color-warning);
}
</style>
