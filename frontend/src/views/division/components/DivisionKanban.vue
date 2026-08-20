<template>
  <div
    class="kanban"
    aria-label="章节分工看板"
  >
    <div
      v-for="column in columns"
      :key="column.key"
      class="kanban__column"
      :class="{ 'kanban__column--drag-over': dragOverColumn === column.key }"
      @dragover.prevent="handleDragOver(column.key)"
      @dragleave="handleDragLeave($event, column.key)"
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
        <!-- 卡片列表：TransitionGroup 提供 FLIP 过渡（进入淡入/离开淡出/位移 0.2s） -->
        <TransitionGroup
          name="kanban-card"
          tag="div"
          class="kanban__column-list"
        >
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
        </TransitionGroup>

        <div
          v-if="getColumnItems(column.key).length === 0"
          class="kanban__empty"
        >
          暂无任务
        </div>

        <!-- 拖拽悬停占位条：提示卡片可放入该泳道 -->
        <div
          v-if="showDropIndicator(column.key)"
          class="kanban__drop-indicator"
        />
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

/** 目标泳道占位条：悬停中且卡片状态与目标不一致（将发生移动）时显示 */
const showDropIndicator = (columnKey: TaskStatus): boolean =>
  dragOverColumn.value === columnKey &&
  !!draggingItem.value &&
  draggingItem.value.status !== columnKey

const handleDragEnd = () => {
  draggingItem.value = null
  dragOverColumn.value = null
}

const handleDragOver = (columnKey: TaskStatus) => {
  dragOverColumn.value = columnKey
}

const handleDragLeave = (e: DragEvent, columnKey: TaskStatus) => {
  // 仅在真正离开泳道（而非进入其子元素）时清除高亮，避免闪烁
  const current = e.currentTarget
  if (
    current instanceof HTMLElement &&
    e.relatedTarget instanceof Node &&
    current.contains(e.relatedTarget)
  ) {
    return
  }
  if (dragOverColumn.value === columnKey) {
    dragOverColumn.value = null
  }
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
  gap: var(--space-3);
  overflow-x: auto;
  padding-bottom: var(--space-2);
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

/* 平板及以下：泳道不再压缩，容器横向滚动浏览全部泳道 */
@media (max-width: 1023px) {
  .kanban {
    overflow-x: auto;
  }
  .kanban__column {
    min-width: 240px;
    flex-shrink: 0;
  }
}

.kanban__column--drag-over {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  animation: kanban-breathe 1s ease-in-out infinite;
}

/* 泳道边框呼吸高亮（拖拽悬停反馈） */
@keyframes kanban-breathe {
  0%,
  100% {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px var(--color-primary-light);
  }
  50% {
    border-color: var(--border-color-strong);
    box-shadow: 0 0 0 0 transparent;
  }
}

.kanban__column-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
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
  padding: var(--space-2);
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* TransitionGroup 渲染容器：与原卡片列表布局一致 */
.kanban__column-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  position: relative;
}

/* 卡片列表过渡（FLIP）：进入淡入、离开淡出、其余卡片位移跟随 0.2s */
.kanban-card-enter-active,
.kanban-card-leave-active {
  transition: opacity 0.2s ease;
}
.kanban-card-enter-from,
.kanban-card-leave-to {
  opacity: 0;
}
.kanban-card-move {
  transition: transform 0.2s ease;
}
/* 离开项脱离文档流，兄弟卡片才能平滑补位 */
.kanban-card-leave-active {
  position: absolute;
  width: 100%;
}

.kanban__card {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--space-3);
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
  padding: var(--space-6) var(--space-3);
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 拖拽占位高亮条 */
.kanban__drop-indicator {
  height: 8px;
  margin-top: var(--space-1);
  border-radius: var(--radius-sm);
  border: 1px dashed var(--color-primary);
  background: var(--color-primary-light);
}
</style>
