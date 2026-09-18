<template>
  <a-tabs
    v-model:activeKey="activeTab"
    class="generate-view__tabs"
  >
    <a-tab-pane
      key="preview"
      tab="章节预览"
    >
      <ChapterPreview
        :selected-chapter="selectedChapter"
        :project-id="projectId"
        :outline="outline"
        :assignment-map="assignmentMap"
        @go-division="emit('go-division')"
      />
    </a-tab-pane>
    <a-tab-pane
      v-if="benchmarkVisible"
      key="benchmark"
      tab="评分对标"
    >
      <ScoreMatchPanel
        :items="benchmarkItems"
        :loading="benchmarkLoading"
        :error="benchmarkError"
        @retry="loadBenchmark"
      />
    </a-tab-pane>
  </a-tabs>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchBenchmark } from '@/api'
import ChapterPreview from './ChapterPreview.vue'
import ScoreMatchPanel from './ScoreMatchPanel.vue'
import type { BenchmarkItem, OutlineItem, AssignmentNode } from '@/types'

const props = defineProps<{
  selectedChapter: string
  projectId: string
  phase: string
  /** 大纲章节（透传给章节预览组件用于全文拼接与全过审判定） */
  outline: OutlineItem[]
  /** 章节分工状态映射（透传） */
  assignmentMap: Map<string, AssignmentNode>
}>()

const emit = defineEmits<{
  (e: 'go-division'): void
}>()

const activeTab = ref('preview')

// 评分对标
const benchmarkItems = ref<BenchmarkItem[]>([])
const benchmarkLoading = ref(false)
const benchmarkLoaded = ref(false)
const benchmarkError = ref('')

const benchmarkVisible = computed(
  () =>
    ['generate', 'review', 'export', 'done'].includes(props.phase),
)

const loadBenchmark = async () => {
  benchmarkLoading.value = true
  benchmarkError.value = ''
  try {
    const { data } = await fetchBenchmark(props.projectId)
    benchmarkItems.value = data?.data?.items ?? []
    benchmarkLoaded.value = true
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    benchmarkError.value = msg || '评分对标加载失败'
  } finally { benchmarkLoading.value = false }
}

watch(
  benchmarkVisible,
  (visible) => { if (visible && !benchmarkLoaded.value && !benchmarkLoading.value) loadBenchmark() },
  { immediate: true },
)
</script>

<style scoped>
.generate-view__tabs {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 0 16px 16px;
}
</style>
