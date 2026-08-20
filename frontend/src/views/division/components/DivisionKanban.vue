<template>
  <div class="kanban">
    <div
      v-for="column in columns"
      :key="column.key"
      class="kanban__column"
      :class="{ 'kanban__column--drag-over': dragOverColumn === column.key }"
      @dragover.prevent="handleDragOver(column.key)"
      @dragleave="handleDragLeave"
      @drop="handleDrop(column.key)"
    >
      <div class="kanban__column-header">
        <span class="kanban__column-title">{{ column.title }}</span>
        <a-tag
          :color="column.color"
          class="kanban__column-count"
        >
          {{ getColumnItems(column.key).length }}
        </a-tag>
      </div>

      <div class="kanban__column-body">
        <div
          v-for="item in getColumnItems(column.key)"
          :key="item.id"
          class="kanban__card"
          :class="{ 'kanban__card--dragging': draggingItem?.id === item.id }"
          draggable="true"
          @dragstart="handleDragStart(item)"
          @dragend="handleDragEnd"
          @click="$emit('select', item)"
        >
          <div class="kanban__card-header">
            <span class="kanban__card-chapter">{{ item.chapter_no }}</span>
            <a-tag
              v-if="item.assignee_name"
              color="blue"
              class="kanban__card-assignee"
            >
              {{ item.assignee_name }}
            </a-tag>
          </div>
          <div
            class="kanban__card-title"
            :title="item.title"
          >
            {{ item.title }}
          </div>
          <div
            v-if="item.updated_at"
            class="kanban__card-time"
          >
            {{ formatTime(item.updated_at) }}
          </div>
        </div>

        <div
          v-if="getColumnItems(column.key).length === 0"
          class="kanban__empty"
        >
          暂无任务
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { AssignmentItem, TaskStatus } from '@/types'

interface KanbanColumn {
  key: TaskStatus
  title: string
  color: string
}

const props = defineProps<{
  items: AssignmentItem[]
}>()

const emit = defineEmits<{
  (e: 'select', item: AssignmentItem): void
  (e: 'move', item: AssignmentItem, targetStatus: TaskStatus): void
}>()

const columns: KanbanColumn[] = [
  { key: 'pending', title: '待领取', color: 'default' },
  { key: 'in_progress', title: '编制中', color: 'processing' },
  { key: 'rejected', title: '被打回', color: 'error' },
  { key: 'submitted', title: '已提审', color: 'warning' },
  { key: 'approved', title: '已通过', color: 'success' },
]

const draggingItem = ref<AssignmentItem | null>(null)
const dragOverColumn = ref<TaskStatus | null>(null)

const getColumnItems = (status: TaskStatus) =>
  props.items.filter((item) => item.status === status)

const handleDragStart = (item: AssignmentItem) => {
  draggingItem.value = item
}

const handleDragEnd = () => {
  draggingItem.value = null
  dragOverColumn.value = null
}

const handleDragOver = (columnKey: TaskStatus) => {
  dragOverColumn.value = columnKey
}

const handleDragLeave = () => {
  dragOverColumn.value = null
}

const handleDrop = (targetStatus: TaskStatus) => {
  if (draggingItem.value && draggingItem.value.status !== targetStatus) {
    emit('move', draggingItem.value, targetStatus)
  }
  draggingItem.value = null
  dragOverColumn.value = null
}

const formatTime = (time: string): string => {
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours < 1) return '刚刚'
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}天前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}
</script>

<style scoped>
.kanban {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.kanban__column {
  flex: 1;
  min-width: 220px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  transition: border-color var(--transition-fast), background-color var(--transition-fast);
}

.kanban__column--drag-over {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.kanban__column-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.kanban__column-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.kanban__column-count {
  margin: 0;
}

.kanban__column-body {
  flex: 1;
  padding: 8px;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kanban__card {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.kanban__card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.kanban__card--dragging {
  opacity: 0.5;
  transform: rotate(2deg);
}

.kanban__card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.kanban__card-chapter {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.kanban__card-assignee {
  margin: 0;
  font-size: 11px;
}

.kanban__card-title {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  margin-bottom: 6px;
}

.kanban__card-time {
  font-size: 11px;
  color: var(--text-tertiary);
}

.kanban__empty {
  text-align: center;
  padding: 24px 12px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
