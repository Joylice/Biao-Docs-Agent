<template>
  <div class="review-view__content">
    <!-- 章节头部 -->
    <div class="review-view__content-header">
      <div class="review-view__content-title">
        <template v-if="viewMode === 'single'">
          <span class="review-view__chapter-no">{{ activeChapter }}</span>
          <span class="review-view__chapter-title">{{ activeChapterTitle }}</span>
          <a-tag color="geekblue">
            提交人：{{ submitter }}
          </a-tag>
          <a-tag :color="currentStatusColor">
            {{ currentStatusText }}
          </a-tag>
        </template>
        <template v-else>
          <span class="review-view__chapter-title">全文预览（{{ fullKeys.length }} {{ hasDivision ? '章正式方案' : '章' }}）</span>
        </template>
      </div>
      <a-radio-group
        :value="viewMode"
        size="small"
        button-style="solid"
        @change="$emit('view-mode-change', $event)"
      >
        <a-radio-button value="single">单章</a-radio-button>
        <a-radio-button value="full">全文</a-radio-button>
      </a-radio-group>
    </div>

    <!-- 废标风险提示（单章模式） -->
    <a-alert
      v-if="viewMode === 'single' && activeChapterRisks.length > 0"
      type="error"
      show-icon
      class="review-view__risk-alert"
      message="废标风险提示"
    >
      <template #description>
        <div
          v-for="(risk, index) in activeChapterRisks"
          :key="index"
          class="review-view__risk-item"
        >
          <strong>{{ risk.clause_no }} {{ risk.title }}</strong>
          <span> — {{ risk.recommendation }}</span>
        </div>
      </template>
    </a-alert>

    <!-- 富文本预览（单章模式） -->
    <a-spin v-if="viewMode === 'single'" :spinning="contentLoading">
      <div class="review-view__paper-wrapper">
        <WordEditor
          v-if="currentHtml"
          ref="editorRef"
          :content="currentHtml"
          :readonly="true"
          :annotations="annotationMarks"
          :active-annotation-id="activeAnnotationId"
          class="review-view__editor"
          @selection-change="$emit('selection-change', $event)"
        />
        <div v-else class="review-view__empty-content">
          暂无内容
        </div>
      </div>
    </a-spin>

    <!-- 全文预览模式 -->
    <div v-else class="review-view__full-content" :ref="(el) => $emit('full-content-mounted', el as HTMLElement | null)">
      <div
        v-for="chapterNo in fullKeys"
        :key="chapterNo"
        :id="`chapter-${chapterNo}`"
        class="review-view__full-chapter"
      >
        <div class="review-view__full-chapter-header">
          <span class="review-view__full-chapter-no">{{ chapterNo }}</span>
          <span class="review-view__full-chapter-title">
            {{ outline.find((c) => c.chapter_no === chapterNo)?.title || '' }}
          </span>
        </div>
        <div class="review-view__full-chapter-body">
          <PaginatedPreview
            v-if="chapterHtmlMap[chapterNo]"
            :fill="false"
            :html="chapterHtmlMap[chapterNo]"
            class="review-view__full-preview"
          />
          <div v-else class="review-view__empty-content">
            暂无内容
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import WordEditor from '@/components/editor/WordEditor.vue'
import PaginatedPreview from '@/components/PaginatedPreview.vue'

defineProps<{
  viewMode: 'single' | 'full'
  activeChapter: string
  activeChapterTitle: string
  submitter: string
  currentStatusColor: string
  currentStatusText: string
  hasDivision: boolean
  fullKeys: string[]
  activeChapterRisks: { clause_no: string; title: string; recommendation: string }[]
  contentLoading: boolean
  currentHtml: string
  annotationMarks: { id: string; from: number; to: number; status: 'open' | 'resolved' }[]
  activeAnnotationId: string | null
  outline: { chapter_no: string; title: string }[]
  chapterHtmlMap: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'view-mode-change', event: { target: { value?: string } }): void
  (e: 'selection-change', sel: { from: number; to: number; text: string } | null): void
  (e: 'full-content-mounted', el: HTMLElement | null): void
}>()

// emit is used via template $emit calls; reference to avoid TS6133
void emit

const editorRef = ref<InstanceType<typeof WordEditor> | null>(null)

defineExpose({
  editorRef,
  scrollToPosition: (pos: number) => editorRef.value?.scrollToPosition(pos),
})
</script>

<style scoped src="../review-view.css"></style>
