<template>
  <div class="empty-state">
    <a-empty :description="description">
      <template #image>
        <slot name="icon">
          <InboxOutlined class="empty-state__icon" />
        </slot>
      </template>
    </a-empty>
    <div
      v-if="$slots.action"
      class="empty-state__action"
    >
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { InboxOutlined } from '@ant-design/icons-vue'

withDefaults(defineProps<{ description?: string }>(), {
  description: '暂无数据',
})
</script>

<style scoped>
.empty-state {
  padding: 48px 16px;
  text-align: center;
}

.empty-state__icon {
  font-size: 48px;
  color: var(--text-disabled);
}

.empty-state__action {
  margin-top: 16px;
}
</style>
