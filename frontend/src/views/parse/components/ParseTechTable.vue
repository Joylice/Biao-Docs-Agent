<template>
  <a-card title="技术需求">
    <template #extra>
      <a-popconfirm
        title="将基于评分点重新梳理衍生需求，确认继续？"
        ok-text="生成"
        cancel-text="取消"
        @confirm="$emit('generate')"
      >
        <a-button size="small" :loading="generateLoading">
          {{ selectedCount > 0 ? `生成技术需求（已选 ${selectedCount} 项）` : '生成技术需求（全部已确认）' }}
        </a-button>
      </a-popconfirm>
    </template>

    <a-table :columns="techColumns" :data-source="techRequirements" :pagination="false" row-key="id" size="middle">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'is_mandatory'">
          <a-tag :color="record.is_mandatory ? 'red' : 'blue'">
            {{ record.is_mandatory ? '强制' : '建议' }}
          </a-tag>
        </template>
        <template v-if="column.key === 'source'">
          <a-tag :color="record.source === 'sp_derived' ? 'green' : 'default'">
            {{ record.source === 'sp_derived' ? '评分点衍生' : '招标原文' }}
          </a-tag>
        </template>
        <template v-if="column.key === 'related_sp'">
          <span v-if="record.related_sp">{{ record.related_sp.clause_no }} {{ record.related_sp.item }}</span>
          <span v-else>—</span>
        </template>
      </template>
    </a-table>
  </a-card>
</template>

<script setup lang="ts">
interface TechRequirement {
  id: string
  seq: number
  description: string
  category: string | null
  is_mandatory: boolean
  source?: string | null
  related_sp?: { clause_no: string; item: string } | null
}

defineProps<{
  techRequirements: TechRequirement[]
  generateLoading: boolean
  selectedCount: number
}>()

defineEmits<{
  (e: 'generate'): void
}>()

const techColumns = [
  { title: '序号', dataIndex: 'seq', key: 'seq', width: 60 },
  { title: '需求描述', dataIndex: 'description', key: 'description' },
  { title: '分类', dataIndex: 'category', key: 'category', width: 100 },
  { title: '类型', key: 'is_mandatory', width: 80 },
  { title: '来源', key: 'source', width: 110 },
  { title: '对应评分点', key: 'related_sp', width: 240 },
]
</script>
