<template>
  <div class="review-chapter-list">
    <div class="review-chapter-list__header">
      <span class="review-chapter-list__title">章节列表</span>
      <a-tag color="blue">
        {{ chapters.length }} 章
      </a-tag>
    </div>
    <div class="review-chapter-list__tree">
      <a-tree
        :tree-data="treeData"
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
          >
            <span class="review-chapter-list__no">
              {{ dataRef.chapter_no }} {{ dataRef.title }}
            </span>
            <a-tag
              :color="chapterStateColor(dataRef.chapter_no)"
              class="review-chapter-list__tag"
            >
              {{ chapterStateText(dataRef.chapter_no) }}
            </a-tag>
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
import { computed } from 'vue'

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
  editDrafts: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'select', chapterNo: string): void
  (e: 'expand', keys: string[]): void
}>()

const chapterKeys = computed(() => Object.keys(props.chapters))

const treeData = computed<ChapterTreeNode[]>(() => {
  const nodes: ChapterTreeNode[] = props.outline.map((c) => ({
    key: c.chapter_no,
    kind: 'chapter',
    chapter_no: c.chapter_no,
    title: c.title,
    selectable: true,
    children: (c.sections || []).map((s, idx) => ({
      key: `${c.chapter_no}-s${idx}`,
      kind: 'section',
      chapter_no: c.chapter_no,
      title: s,
      selectable: false,
    })),
  }))
  const outlineNos = new Set(props.outline.map((c) => c.chapter_no))
  for (const no of chapterKeys.value) {
    if (!outlineNos.has(no)) {
      nodes.push({ key: no, kind: 'chapter', chapter_no: no, title: '', selectable: true })
    }
  }
  return nodes
})

const hasEditDraft = (chapterNo: string): boolean => {
  const draft = props.editDrafts[chapterNo]
  return draft !== undefined && draft !== props.chapters[chapterNo]
}

const chapterStateText = (chapterNo: string): string => {
  if (props.reviewFeedback[chapterNo]) return '待重写'
  if (hasEditDraft(chapterNo)) return '已修改'
  return '待审'
}

const chapterStateColor = (chapterNo: string): string => {
  if (props.reviewFeedback[chapterNo]) return 'orange'
  if (hasEditDraft(chapterNo)) return 'blue'
  return 'default'
}

const onTreeSelect = (keys: string[]) => {
  if (keys.length > 0) emit('select', keys[0])
}

const onTreeExpand = (keys: string[]) => {
  emit('expand', keys)
}
</script>

<style scoped>
.review-chapter-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.review-chapter-list__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.review-chapter-list__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.review-chapter-list__tree {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.review-chapter-list__node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.review-chapter-list__no {
  font-size: 13px;
  font-weight: 500;
}

.review-chapter-list__tag {
  flex-shrink: 0;
  font-size: 11px;
  line-height: 16px;
}

.review-chapter-list__section {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
