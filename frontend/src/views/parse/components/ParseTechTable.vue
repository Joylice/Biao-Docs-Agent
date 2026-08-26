<template>
  <a-card title="技术需求">
    <template #extra>
      <div class="parse-tech-table__header">
        <span v-if="confirmedCount === 0" class="parse-tech-table__hint-text">
          请先在「评分点」Tab 中确认评分点
        </span>
        <a-popconfirm
          v-else
          :title="`将基于已确认的 ${confirmedCount} 条评分点生成技术需求，确认继续？`"
          ok-text="生成"
          cancel-text="取消"
          @confirm="$emit('generate')"
        >
          <a-button
            size="small"
            type="primary"
            :loading="generateLoading"
          >
            生成技术需求
          </a-button>
        </a-popconfirm>
        <a-button
          v-if="confirmedCount === 0"
          size="small"
          disabled
        >
          生成技术需求
        </a-button>
      </div>
    </template>

    <a-table
      :columns="techColumns"
      :data-source="techRequirements"
      :pagination="false"
      row-key="id"
      size="middle"
    >
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
          <span v-if="record.related_sp">
            {{ record.related_sp.clause_no }} {{ record.related_sp.item }}
          </span>
          <a-tag
            v-else
            color="default"
          >
            未关联
          </a-tag>
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
  confirmedCount: number
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

<style scoped>
.parse-tech-table__header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.parse-tech-table__hint-text {
  font-size: var(--font-size-sm);
  color: var(--color-warning);
}
</style>
