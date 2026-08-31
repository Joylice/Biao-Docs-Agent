<template>
  <div class="review-chapter-list">
    <div class="review-chapter-list__header">
      <span class="review-chapter-list__title">章节导航</span>
      <a-tag color="blue">
        {{ filteredKeys.length }} / {{ chapters.length }} 章
      </a-tag>
    </div>

    <!-- 筛选标签 -->
    <div class="review-chapter-list__filters">
      <a-radio-group
        v-model:value="filter"
        size="small"
        button-style="solid"
      >
        <a-radio-button value="all">全部</a-radio-button>
        <a-radio-button value="pending">未审</a-radio-button>
        <a-radio-button value="approved">通过</a-radio-button>
        <a-radio-button value="rejected">打回</a-radio-button>
        <a-radio-button value="annotated">批注</a-radio-button>
      </a-radio-group>
    </div>

    <!-- 章节树 -->
    <div class="review-chapter-list__tree">
      <a-tree
        :tree-data="filteredTreeData"
        :selected-keys="[activeChapter]"
        :expanded-keys="expandedKeys"
        block-node
        @select="onTreeSelect"
        @expand="onTreeExpand"
      >
        <template #title="{ dataRef }">
          <div
            v-if="dataRef.kind === 'chapter'"
            class="review-chapter-list__node"
            :class="{ 'review-chapter-list__node--active': dataRef.chapter_no === activeChapter }"
          >
            <span class="review-chapter-list__node-left">
              <span
                class="review-chapter-list__status-dot"
                :class="`review-chapter-list__status-dot--${chapterStatuses[dataRef.chapter_no] || 'pending'}`"
              />
              <span class="review-chapter-list__no">
                {{ dataRef.chapter_no }}
              </span>
              <span class="review-chapter-list__node-title">
                {{ dataRef.title }}
              </span>
            </span>
            <span class="review-chapter-list__node-right">
              <a-badge
                v-if="(annotationCounts[dataRef.chapter_no] || 0) > 0"
                :count="annotationCounts[dataRef.chapter_no]"
                :number-style="{ backgroundColor: '#1890ff', fontSize: '10px', height: '16px', lineHeight: '16px' }"
              />
            </span>
          </div>
          <span
            v-else
            class="review-chapter-list__section"
          >{{ dataRef.title }}</span>
        </template>
      </a-tree>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface OutlineNode {
  chapter_no: string
  title: string
  sections?: string[]
}

interface ChapterTreeNode {
  key: string
  kind: 'chapter' | 'section'
  chapter_no: string
  title: string
  selectable: boolean
  children?: ChapterTreeNode[]
}

const props = defineProps<{
  outline: OutlineNode[]
  chapters: Record<string, string>
  activeChapter: string
  expandedKeys: string[]
  reviewFeedback: Record<string, string>
  annotationCounts: Record<string, number>
  chapterStatuses: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'select', chapterNo: string): void
  (e: 'expand', keys: string[]): void
}>()

const filter = ref<'all' | 'pending' | 'approved' | 'rejected' | 'annotated'>('all')

const chapterKeys = computed(() => Object.keys(props.chapters))

const filteredKeys = computed(() => {
  return chapterKeys.value.filter((no) => {
    switch (filter.value) {
      case 'pending':
        return props.chapterStatuses[no] === 'pending'
      case 'approved':
        return props.chapterStatuses[no] === 'approved'
      case 'rejected':
        return props.chapterStatuses[no] === 'rejected'
      case 'annotated':
        return (props.annotationCounts[no] || 0) > 0
      default:
        return true
    }
  })
})

const allTreeData = computed<ChapterTreeNode[]>(() => {
  const nodes: ChapterTreeNode[] = props.outline.map((c) => ({
    key: c.chapter_no,
    kind: 'chapter',
    chapter_no: c.chapter_no,
    title: c.title,
    selectable: true,
    children: (c.sections || []).map((s, i) => ({
      key: `${c.chapter_no}.${i + 1}`,
      kind: 'section' as const,
      chapter_no: '',
      title: s,
      selectable: false,
    })),
  }))
  return nodes
})

const filteredTreeData = computed<ChapterTreeNode[]>(() => {
  if (filter.value === 'all') return allTreeData.value
  // 筛选时只显示匹配的章节（保留子节）
  return allTreeData.value.filter((node) =>
    filteredKeys.value.includes(node.chapter_no),
  )
})

const onTreeSelect = (keys: any) => {
  if (keys.length > 0) emit('select', keys[0])
}

const onTreeExpand = (keys: any) => {
  emit('expand', keys)
}
</script>

<style scoped>
.review-chapter-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-elevated, #1f1f1f);
  border: 1px solid var(--border-color, #303030);
  border-radius: 8px;
  overflow: hidden;
}

.review-chapter-list__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #303030);
}

.review-chapter-list__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.review-chapter-list__filters {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color, #303030);
}

.review-chapter-list__filters :deep(.ant-radio-button-wrapper) {
  font-size: 11px;
  padding: 0 8px;
}

.review-chapter-list__tree {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.review-chapter-list__node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 4px 0;
  gap: 4px;
}

.review-chapter-list__node-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.review-chapter-list__status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.review-chapter-list__status-dot--pending {
  background: var(--text-tertiary, #666);
}

.review-chapter-list__status-dot--approved {
  background: #52c41a;
}

.review-chapter-list__status-dot--rejected {
  background: #fa8c16;
}

.review-chapter-list__no {
  font-size: 12px;
  color: var(--primary-color, #1890ff);
  font-weight: 500;
  flex-shrink: 0;
}

.review-chapter-list__node-title {
  font-size: 13px;
  color: var(--text-primary, #e0e0e0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-chapter-list__node--active .review-chapter-list__node-title {
  font-weight: 600;
}

.review-chapter-list__node-right {
  flex-shrink: 0;
}

.review-chapter-list__section {
  font-size: 12px;
  color: var(--text-secondary, #999);
  padding-left: 20px;
}

/* 树节点选中样式 */
.review-chapter-list__tree :deep(.ant-tree-node-selected) {
  background: rgba(24, 144, 255, 0.1) !important;
  border-left: 3px solid var(--primary-color, #1890ff);
}

.review-chapter-list__tree :deep(.ant-tree-treenode) {
  padding: 0;
  width: 100%;
}

.review-chapter-list__tree :deep(.ant-tree-node-content-wrapper) {
  flex: 1;
  overflow: hidden;
}
</style>
