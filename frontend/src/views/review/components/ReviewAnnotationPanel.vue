<template>
  <div class="review-view__annotation-panel">
    <!-- 选区提示 -->
    <div
      v-if="currentSelectionText"
      class="review-view__selection-hint"
    >
      <span class="review-view__selection-label">已选中文字：</span>
      <span class="review-view__selection-text">"{{ currentSelectionText }}"</span>
    </div>
    <div class="review-view__annotation-actions">
      <a-input
        v-model:value="newAnnotationProxy"
        :placeholder="currentSelectionText ? '对选中文字添加批注...' : '添加批注（可先在正文中选中文字）...'"
        :disabled="addingAnnotation"
        @press-enter="$emit('add', activeChapter)"
      >
        <template #addonAfter>
          <a-button
            type="primary"
            :loading="addingAnnotation"
            @click="$emit('add', activeChapter)"
          >
            添加
          </a-button>
        </template>
      </a-input>
    </div>
    <!-- 筛选 -->
    <div class="review-view__annotation-filter">
      <a-radio-group
        v-model:value="annotationFilterProxy"
        size="small"
        button-style="solid"
      >
        <a-radio-button value="open">
          未解决 ({{ openAnnotationCount }})
        </a-radio-button>
        <a-radio-button value="resolved">
          已解决 ({{ resolvedAnnotationCount }})
        </a-radio-button>
        <a-radio-button value="all">全部</a-radio-button>
      </a-radio-group>
    </div>
    <a-spin :spinning="annotationsLoading">
      <a-empty
        v-if="filteredAnnotations.length === 0"
        description="暂无批注"
        :image="Empty.PRESENTED_IMAGE_SIMPLE"
      />
      <div
        v-else
        class="review-view__annotation-list"
      >
        <div
          v-for="item in filteredAnnotations"
          :key="item.id"
          class="review-view__annotation-item"
          :class="{
            'review-view__annotation-item--active': activeAnnotationId === item.id,
            'review-view__annotation-item--resolved': item.status === 'resolved',
          }"
          @click="$emit('locate', item)"
        >
          <div class="review-view__annotation-header">
            <span class="review-view__annotation-author">
              {{ item.created_by_name || '未知用户' }}
            </span>
            <a-tag
              :color="item.status === 'resolved' ? 'green' : 'orange'"
              class="review-view__annotation-status"
            >
              {{ item.status === 'resolved' ? '已解决' : '未解决' }}
            </a-tag>
          </div>
          <div
            v-if="item.selection?.text"
            class="review-view__annotation-quote"
          >
            "{{ item.selection.text.length > 50 ? item.selection.text.slice(0, 50) + '...' : item.selection.text }}"
          </div>
          <div class="review-view__annotation-content">
            {{ item.content }}
          </div>
          <div class="review-view__annotation-footer">
            <span class="review-view__annotation-time">
              {{ formatTime(item.created_at) }}
            </span>
            <span class="review-view__annotation-btns">
              <a-button
                type="link"
                size="small"
                @click.stop="$emit('toggle', activeChapter, item.id)"
              >
                {{ item.status === 'resolved' ? '重新打开' : '标记解决' }}
              </a-button>
              <a-button
                v-if="item.created_by === currentUserId"
                type="link"
                size="small"
                danger
                @click.stop="$emit('delete', activeChapter, item.id)"
              >
                删除
              </a-button>
            </span>
          </div>
        </div>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Empty } from 'ant-design-vue'
import type { AnnotationItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'

const props = defineProps<{
  currentSelectionText: string
  newAnnotation: string
  addingAnnotation: boolean
  annotationsLoading: boolean
  annotationFilter: 'open' | 'resolved' | 'all'
  filteredAnnotations: AnnotationItem[]
  openAnnotationCount: number
  resolvedAnnotationCount: number
  activeAnnotationId: string | null
  activeChapter: string
}>()

const emit = defineEmits<{
  (e: 'update:newAnnotation', v: string): void
  (e: 'update:annotationFilter', v: 'open' | 'resolved' | 'all'): void
  (e: 'add', chapter: string): void
  (e: 'locate', item: AnnotationItem): void
  (e: 'toggle', chapter: string, id: string): void
  (e: 'delete', chapter: string, id: string): void
}>()

const newAnnotationProxy = computed({
  get: () => props.newAnnotation,
  set: (v: string) => emit('update:newAnnotation', v),
})

const annotationFilterProxy = computed({
  get: () => props.annotationFilter,
  set: (v: 'open' | 'resolved' | 'all') => emit('update:annotationFilter', v),
})

const formatTime = (time: string): string => {
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}
</script>

<style scoped src="../review-view.css"></style>
