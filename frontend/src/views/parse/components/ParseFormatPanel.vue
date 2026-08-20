<template>
  <a-card title="格式要求汇总">
    <template #extra>
      <a-space>
        <a-button
          size="small"
          @click="$emit('add-item')"
        >
          新增条目
        </a-button>
        <a-button
          size="small"
          :loading="formatSaving"
          @click="$emit('save')"
        >
          保存
        </a-button>
      </a-space>
    </template>

    <a-alert
      v-if="formatRequirements.length === 0"
      type="info"
      show-icon
      message="未提取到格式要求，可手动新增（字体字号、行距、页边距等将应用到 Word 导出排版）"
    />

    <div
      v-else
      class="parse-format__list"
    >
      <div
        v-for="group in formatGroups"
        :key="group.category"
        class="parse-format__group"
      >
        <div class="parse-format__group-label">
          {{ formatCategoryLabel(group.category) }}
        </div>
        <div
          v-for="item in group.items"
          :key="item.key"
          class="parse-format__item"
        >
          <a-select
            v-model:value="item.category"
            :options="formatCategoryOptions"
            style="width: 140px"
            size="small"
          />
          <a-input
            v-model:value="item.requirement"
            size="small"
            placeholder="格式要求描述，如：正文小四号仿宋、1.5 倍行距"
          />
          <a-button
            size="small"
            type="text"
            danger
            @click="$emit('remove-item', item)"
          >
            删除
          </a-button>
        </div>
      </div>
    </div>
  </a-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface FormatRequirementItem {
  key: string
  category: string
  requirement: string
}

const props = defineProps<{
  formatRequirements: FormatRequirementItem[]
  formatSaving: boolean
}>()

defineEmits<{
  (e: 'add-item'): void
  (e: 'remove-item', item: FormatRequirementItem): void
  (e: 'save'): void
}>()

const FORMAT_CATEGORIES: { value: string; label: string }[] = [
  { value: 'font_body', label: '正文字体字号' },
  { value: 'font_heading', label: '标题字体字号' },
  { value: 'line_spacing', label: '行距' },
  { value: 'margin', label: '页边距' },
  { value: 'page_setup', label: '页面设置' },
  { value: 'binding', label: '装订' },
  { value: 'page_number', label: '页码' },
  { value: 'toc', label: '目录' },
  { value: 'chapter_format', label: '章节格式要求' },
  { value: 'other', label: '其他' },
]

const formatCategoryOptions = FORMAT_CATEGORIES
const formatCategoryLabel = (value: string) => FORMAT_CATEGORIES.find((c) => c.value === value)?.label || value

const formatGroups = computed(() => {
  const groups: { category: string; items: FormatRequirementItem[] }[] = []
  for (const cat of FORMAT_CATEGORIES.map((c) => c.value)) {
    const items = props.formatRequirements.filter((it) => it.category === cat)
    if (items.length > 0) groups.push({ category: cat, items })
  }
  const known = new Set(FORMAT_CATEGORIES.map((c) => c.value))
  const unknown = props.formatRequirements.filter((it) => !known.has(it.category))
  if (unknown.length > 0) groups.push({ category: 'other', items: unknown })
  return groups
})
</script>

<style scoped>
.parse-format__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.parse-format__group-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.parse-format__item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
</style>
