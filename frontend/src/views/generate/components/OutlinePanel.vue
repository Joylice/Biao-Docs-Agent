<template>
  <div class="outline-panel">
    <div class="outline-panel__header">
      <span class="outline-panel__title">方案大纲</span>
      <a-tag
        v-if="awaitingConfirm"
        color="warning"
      >
        待确认
      </a-tag>
      <a-tag
        v-else
        color="success"
      >
        已确认
      </a-tag>
    </div>

    <div class="outline-panel__tree">
      <a-tree
        :tree-data="treeData"
        :selected-keys="selectedKeys"
        :default-expand-all="true"
        @select="handleSelect"
      >
        <template #title="node">
          <span class="outline-panel__node-title">{{ node.title }}</span>
          <template v-if="node.assigneeName">
            <span class="outline-panel__assignee">{{ node.assigneeName }}</span>
            <a-tag
              v-if="node.assignStatus && statusMeta[node.assignStatus]"
              class="outline-panel__tag"
              :color="statusMeta[node.assignStatus].color"
            >
              {{ statusMeta[node.assignStatus].text }}
            </a-tag>
          </template>
        </template>
      </a-tree>
    </div>

    <div
      v-if="outline.length === 0"
      class="outline-panel__empty"
    >
      <EmptyState description="暂无大纲" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { OutlineItem, OutlineSection, AssignmentNode } from '@/types'
import EmptyState from '@/components/EmptyState.vue'

interface TreeDataItem {
  key: string
  title: string
  chapterNo?: string
  sectionNo?: string
  children?: TreeDataItem[]
  assigneeName?: string
  assignStatus?: string | null
}

const props = defineProps<{
  outline: OutlineItem[]
  selectedChapter: string
  awaitingConfirm: boolean
  assignmentMap: Map<string, AssignmentNode>
}>()

const emit = defineEmits<{
  (e: 'select', chapterNo: string): void
}>()

// 当前选中的子章节 key（用于高亮子节点）
const selectedSectionKey = ref('')

const statusMeta: Record<string, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

const assignInfoOf = (chapterNo: string) => {
  const a = props.assignmentMap.get(chapterNo)
  if (!a || !a.assignee_name) return {}
  return { assigneeName: a.assignee_name, assignStatus: a.status }
}

const toSectionTreeData = (sections: OutlineSection[], prefix: string): TreeDataItem[] => {
  if (!Array.isArray(sections)) return []
  return sections.map((s, i) => {
    const no = `${prefix}.${i + 1}`
    if (typeof s === 'string') {
      return { key: `sub-${no}`, title: `${no} ${s}`, chapterNo: prefix, sectionNo: no, ...assignInfoOf(no) }
    }
    return {
      key: `sub-${no}`,
      title: `${no} ${s.title}`,
      chapterNo: prefix,
      sectionNo: no,
      ...assignInfoOf(no),
      children: s.children?.length ? toSectionTreeData(s.children, no) : undefined,
    }
  })
}

const treeData = computed<TreeDataItem[]>(() =>
  props.outline.map((c) => ({
    key: `ch-${c.chapter_no}`,
    title: `${c.chapter_no} ${c.title}`,
    chapterNo: c.chapter_no,
    ...assignInfoOf(c.chapter_no),
    children: toSectionTreeData(c.sections ?? [], c.chapter_no),
  })),
)

// 选中的 keys：父章节 + 当前选中的子章节
const selectedKeys = computed(() => {
  const keys: string[] = []
  if (props.selectedChapter) keys.push(`ch-${props.selectedChapter}`)
  if (selectedSectionKey.value) keys.push(selectedSectionKey.value)
  return keys
})

// 当父章节变化时，清空子章节选中
watch(() => props.selectedChapter, () => {
  selectedSectionKey.value = ''
})

const handleSelect = (keys: Array<string | number>) => {
  const key = String(keys[0])
  if (!key) return
  if (key.startsWith('ch-')) {
    selectedSectionKey.value = ''
    emit('select', key.slice(3))
  } else if (key.startsWith('sub-')) {
    selectedSectionKey.value = key
    // 子章节 emit 父章节号，用于获取章节内容
    const sectionNo = key.slice(4)
    const chapterNo = sectionNo.split('.')[0]
    emit('select', chapterNo)
  }
}
</script>

<style scoped>
.outline-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.outline-panel__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.outline-panel__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.outline-panel__tree {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.outline-panel__node-title {
  font-size: 13px;
}

.outline-panel__assignee {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.outline-panel__tag {
  margin-left: 4px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 14px;
}

.outline-panel__empty {
  padding: 24px;
}
</style>
