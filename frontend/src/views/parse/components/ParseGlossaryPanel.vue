<template>
  <div class="parse-glossary-panel">
    <a-divider />
    <h3 class="parse-glossary-panel__title">术语表</h3>
    <a-table
      :columns="columns"
      :data-source="glossary"
      :pagination="false"
      row-key="term"
      size="small"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'canonical'">
          <a-typography-text strong>{{ record.canonical }}</a-typography-text>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import type { GlossaryItem } from '@/types'

defineProps<{
  glossary: GlossaryItem[]
}>()

const columns = [
  { title: '缩写/别名', dataIndex: 'term', key: 'term', width: 180 },
  { title: '规范全称', dataIndex: 'canonical', key: 'canonical', width: 200 },
  { title: '说明', dataIndex: 'desc', key: 'desc' },
]
</script>

<style scoped>
.parse-glossary-panel {
  margin-top: 16px;
}

.parse-glossary-panel__title {
  margin: 0 0 12px 0;
  font-size: var(--font-size-md, 16px);
  font-weight: 600;
}
</style>
