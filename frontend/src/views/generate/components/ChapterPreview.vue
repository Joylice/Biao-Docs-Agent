<template>
  <div class="chapter-preview">
    <div class="chapter-preview__header">
      <div class="chapter-preview__title">
        <a-tag
          v-if="currentChapter"
          color="blue"
        >
          生成中：章节 {{ currentChapter }}
        </a-tag>
        <a-tag
          v-if="generating"
          color="processing"
        >
          <template #icon>
            <SyncOutlined spin />
          </template>
          正在生成
        </a-tag>
        <a-tag
          v-else-if="generated"
          color="success"
        >
          已生成
        </a-tag>
        <a-tag v-else>
          待生成
        </a-tag>
      </div>
      <div class="chapter-preview__actions">
        <a-button
          v-if="canGoDivision"
          size="small"
          @click="$emit('go-division')"
        >
          去编制
        </a-button>
        <a-button
          v-if="selectedChapter"
          size="small"
          @click="$emit('close')"
        >
          关闭
        </a-button>
      </div>
    </div>

    <div class="chapter-preview__progress">
      <a-progress
        :percent="Math.round(progress * 100)"
        :status="progressStatus"
        size="small"
      />
    </div>

    <div class="chapter-preview__content">
      <template v-if="selectedChapter">
        <a-card
          :title="`章节 ${selectedChapter}`"
          class="chapter-preview__card"
        >
          <MarkdownRenderer
            v-if="displayChapters[selectedChapter]"
            :source="displayChapters[selectedChapter]"
            :project-id="projectId"
          />
          <LoadingSkeleton
            v-else
            :rows="6"
          />
        </a-card>
      </template>
      <EmptyState
        v-else
        description="从左侧大纲选择章节查看内容"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { SyncOutlined } from '@ant-design/icons-vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

const props = defineProps<{
  selectedChapter: string
  currentChapter: string
  displayChapters: Record<string, string>
  progress: number
  generating: boolean
  generated: boolean
  projectId: string
  canGoDivision: boolean
}>()

defineEmits<{
  (e: 'close'): void
  (e: 'go-division'): void
}>()

const progressStatus = computed(() => {
  if (props.progress >= 1) return 'success'
  if (props.generating) return 'active'
  return 'normal'
})
</script>

<style scoped>
.chapter-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chapter-preview__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.chapter-preview__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chapter-preview__progress {
  margin-bottom: 16px;
}

.chapter-preview__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.chapter-preview__card {
  min-height: 320px;
}
</style>
