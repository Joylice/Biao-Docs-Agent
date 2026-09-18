<template>
  <div class="review-chapter-list">
    <div class="review-chapter-list__header">
      <span class="review-chapter-list__title">章节导航</span>
      <a-tag color="blue">
        {{ filteredKeys.length }} / {{ unitKeys.length }} {{ mode === 'division' ? '节' : '章' }}
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

    <!-- 状态点图例（色点含义说明） -->
    <div class="review-chapter-list__legend">
      <span
        v-for="it in legendItems"
        :key="it.key"
        class="review-chapter-list__legend-item"
      >
        <span
          class="review-chapter-list__legend-dot"
          :class="`review-chapter-list__legend-dot--${it.color}`"
        />
        {{ it.label }}
      </span>
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
          <!-- 可审节点：章（AI 模式）/ 子节（分工模式） -->
          <div
            v-if="dataRef.selectable"
            class="review-chapter-list__node"
            :class="{ 'review-chapter-list__node--active': dataRef.chapter_no === activeChapter }"
          >
            <span class="review-chapter-list__node-left">
              <span
                class="review-chapter-list__status-dot"
                :class="`review-chapter-list__status-dot--${dotStatusOf(dataRef.chapter_no)}`"
              />
              <span class="review-chapter-list__no">
                {{ dataRef.chapter_no }}
              </span>
              <span
                class="review-chapter-list__node-title"
                :title="dataRef.title"
              >
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

          <!-- 分工模式：章级分组行（聚合，不可直接审） -->
          <div
            v-else-if="mode === 'division' && dataRef.kind === 'chapter'"
            class="review-chapter-list__chapter-group"
          >
            <span class="review-chapter-list__group-left">
              <span class="review-chapter-list__group-no">{{ dataRef.chapter_no }}</span>
              <span
                class="review-chapter-list__group-title"
                :title="dataRef.title"
              >{{ dataRef.title }}</span>
            </span>
            <span class="review-chapter-list__group-right">
              <span
                v-if="groupApprovedText[dataRef.chapter_no]"
                class="review-chapter-list__group-approved"
              >
                {{ groupApprovedText[dataRef.chapter_no] }}
              </span>
            </span>
          </div>

          <!-- 大纲子节占位（AI 模式：仅标题不可点） -->
          <span
            v-else
            class="review-chapter-list__section"
            :title="dataRef.title"
          >{{ dataRef.title }}</span>
        </template>
      </a-tree>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { OutlineSection } from '@/types/outline'

interface OutlineNode {
  chapter_no: string
  title: string
  sections?: OutlineSection[]
}

interface ChapterTreeNode {
  key: string
  kind: 'chapter' | 'section'
  chapter_no: string
  title: string
  selectable: boolean
  children?: ChapterTreeNode[]
}

const props = withDefaults(defineProps<{
  outline: OutlineNode[]
  chapters: Record<string, string>
  activeChapter: string
  expandedKeys: string[]
  reviewFeedback: Record<string, string>
  annotationCounts: Record<string, number>
  chapterStatuses: Record<string, string>
  /** 树模式：chapter=AI 生成模式（章级可审）；division=分工模式（子节可审、章分组） */
  mode?: 'chapter' | 'division'
  /** 分工模式审阅单元编号集合（子节/章号）；缺省取 chapters keys */
  unitKeys?: string[]
  /** 分工原始状态（五态：pending/in_progress/submitted/approved/rejected），用于状态点配色 */
  rawStatuses?: Record<string, string>
}>(), {
  mode: 'chapter',
  unitKeys: undefined,
  rawStatuses: undefined,
})

const emit = defineEmits<{
  (e: 'select', chapterNo: string): void
  (e: 'expand', keys: string[]): void
}>()

const filter = ref<'all' | 'pending' | 'approved' | 'rejected' | 'annotated'>('all')

/** 状态点图例：division 含"已提审"（蓝），AI 章模式无该态 */
const legendItems = computed(() => {
  const base = [
    { key: 'pending', label: '未审', color: 'pending' },
    { key: 'approved', label: '通过', color: 'approved' },
    { key: 'rejected', label: '打回', color: 'rejected' },
  ]
  if (props.mode === 'division') {
    return [
      { key: 'pending', label: '未审', color: 'pending' },
      { key: 'submitted', label: '已提审', color: 'submitted' },
      { key: 'approved', label: '通过', color: 'approved' },
      { key: 'rejected', label: '打回', color: 'rejected' },
    ]
  }
  return base
})

const unitKeys = computed(() => props.unitKeys ?? Object.keys(props.chapters))

const dotStatusOf = (no: string): string => {
  if (props.mode === 'division' && props.rawStatuses) {
    const raw = props.rawStatuses[no]
    if (raw === 'approved' || raw === 'rejected' || raw === 'submitted') return raw
  }
  return props.chapterStatuses[no] || 'pending'
}

const filteredKeys = computed(() => {
  return unitKeys.value.filter((no) => {
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

/** 分工模式：章下已通过子节计数文案（如 2/6） */
const groupApprovedText = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  if (props.mode !== 'division') return map
  for (const node of props.outline) {
    const no = node.chapter_no
    const subs = unitKeys.value.filter((k) => k.startsWith(`${no}.`))
    if (subs.length === 0) continue
    const approved = subs.filter((k) => props.chapterStatuses[k] === 'approved').length
    map[no] = `${approved}/${subs.length} 通过`
  }
  return map
})

/**
 * 大纲子节标题归一化：sections 元素兼容 string 与 {title, children} 两种形态，
 * 直接取展示文本（此前把对象当字符串渲染 → Vue 插值输出 JSON 字面量 {"title":…}）。
 */
const sectionTitleOf = (s: OutlineSection): string =>
  typeof s === 'string' ? s : s.title ?? ''

/** 递归展开章节下子节树（编号由位置推导，层级支持到任意深度） */
const toSectionNodes = (sections: OutlineSection[], parentNo: string): ChapterTreeNode[] =>
  sections.map((s, i) => {
    const no = `${parentNo}.${i + 1}`
    const kids = typeof s === 'object' && Array.isArray(s.children) ? s.children : undefined
    return {
      key: no,
      kind: 'section' as const,
      chapter_no: no,
      title: sectionTitleOf(s),
      selectable: false,
      children: kids && kids.length > 0 ? toSectionNodes(kids, no) : undefined,
    }
  })

const allTreeData = computed<ChapterTreeNode[]>(() => {
  if (props.mode === 'chapter') {
    // AI 模式：章级可审，子节仅展示（selectable=false 不会被树选中）
    return props.outline.map((c) => ({
      key: c.chapter_no,
      kind: 'chapter' as const,
      chapter_no: c.chapter_no,
      title: c.title,
      selectable: true,
      children: toSectionNodes(c.sections ?? [], c.chapter_no),
    }))
  }
  // 分工模式：章 = 分组行，子节（分工审阅单元）= 可审节点
  const unitSet = new Set(unitKeys.value)
  return props.outline
    .map((c) => {
      const children = toSectionNodes(c.sections ?? [], c.chapter_no)
        .filter((x) => unitSet.has(x.chapter_no))
        .map((x) => ({ ...x, selectable: true }))
      return {
        key: c.chapter_no,
        kind: 'chapter' as const,
        chapter_no: c.chapter_no,
        title: c.title,
        selectable: false,
        children,
      }
    })
    .filter((n) => (n.children?.length ?? 0) > 0 || unitSet.has(n.chapter_no))
})

const filteredTreeData = computed<ChapterTreeNode[]>(() => {
  if (filter.value === 'all') return allTreeData.value
  if (props.mode === 'division') {
    // 筛选命中子节的章（保留其 children 树）
    return allTreeData.value
      .map((node) => ({
        ...node,
        children: (node.children || []).filter((c) => filteredKeys.value.includes(c.chapter_no)),
      }))
      .filter((node) => (node.children?.length ?? 0) > 0 || filteredKeys.value.includes(node.chapter_no))
  }
  return allTreeData.value.filter((node) => filteredKeys.value.includes(node.chapter_no))
})

const onTreeSelect = (keys: Array<string | number>) => {
  if (keys.length > 0) emit('select', String(keys[0]))
}

const onTreeExpand = (keys: Array<string | number>) => {
  emit('expand', keys.map(String))
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
  padding: 10px 16px 9px;
  border-bottom: 1px solid var(--border-color, #303030);
}

.review-chapter-list__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.review-chapter-list__filters {
  padding: 7px 10px 5px;
  border-bottom: none;
}

.review-chapter-list__filters :deep(.ant-radio-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.review-chapter-list__filters :deep(.ant-radio-button-wrapper) {
  font-size: 11px;
  padding: 0 6px;
}

/* 状态图例行 */
.review-chapter-list__legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
  padding: 3px 14px 7px;
  border-bottom: 1px solid var(--border-color, #303030);
  font-size: 11px;
  color: var(--text-tertiary, #999);
}

.review-chapter-list__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  line-height: 1;
}

.review-chapter-list__legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.review-chapter-list__legend-dot--pending {
  background: var(--text-tertiary, #666);
}

.review-chapter-list__legend-dot--submitted {
  background: #1890ff;
}

.review-chapter-list__legend-dot--approved {
  background: #52c41a;
}

.review-chapter-list__legend-dot--rejected {
  background: #fa8c16;
}

.review-chapter-list__tree {
  flex: 1;
  overflow-y: auto;
  padding: 2px 0 14px; /* 底部留白避免内容恰好顶满 */
}

.review-chapter-list__node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 3px 4px;
  gap: 4px;
  border-radius: 4px;
  transition: background-color 0.15s ease;
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

.review-chapter-list__status-dot--submitted {
  background: #1890ff;
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

.review-chapter-list__node-right {
  flex-shrink: 0;
}

/* 分工模式：章级分组行 */
.review-chapter-list__chapter-group {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 3px 4px;
  gap: 4px;
  border-radius: 4px;
  cursor: default;
  user-select: none;
  transition: background-color 0.15s ease;
}

.review-chapter-list__group-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.review-chapter-list__group-no {
  font-size: 12px;
  color: var(--text-secondary, #999);
  font-weight: 600;
  flex-shrink: 0;
}

.review-chapter-list__group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #bbb);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-chapter-list__group-right {
  flex-shrink: 0;
}

.review-chapter-list__group-approved {
  font-size: 11px;
  color: #52c41a;
}

.review-chapter-list__section {
  font-size: 12px;
  color: var(--text-secondary, #999);
  padding-left: 20px;
}

/* 行 hover：可审节点与分组行均有浅色反馈（选中蓝底优先） */
.review-chapter-list__tree :deep(.ant-tree-treenode:hover) .review-chapter-list__node,
.review-chapter-list__tree :deep(.ant-tree-treenode:hover) .review-chapter-list__chapter-group {
  background: rgba(148, 163, 184, 0.12);
}

.review-chapter-list__tree :deep(.ant-tree-treenode:hover) .review-chapter-list__chapter-group {
  background: rgba(24, 144, 255, 0.06);
}

/* 树节点选中样式：加深背景 + 左侧主色条 + 圆角 */
.review-chapter-list__tree :deep(.ant-tree-node-selected) {
  background: rgba(24, 144, 255, 0.16) !important;
  border-left: 3px solid var(--primary-color, #1890ff);
  border-radius: 4px;
}

/* 选中行文字高亮（编号/标题跟随主色） */
.review-chapter-list__node--active .review-chapter-list__node-title {
  font-weight: 600;
}

.review-chapter-list__tree :deep(.ant-tree-node-selected) .review-chapter-list__node-title {
  color: var(--primary-color, #1890ff);
}

.review-chapter-list__tree :deep(.ant-tree-node-selected) .review-chapter-list__no {
  color: var(--primary-color, #1890ff);
  font-weight: 600;
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
