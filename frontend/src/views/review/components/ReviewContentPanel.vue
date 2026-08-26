<template>
  <div class="review-content">
    <!-- 顶部操作条 -->
    <div class="review-content__toolbar">
      <a-segmented
        :value="mode"
        :options="modeOptions"
        @update:value="$emit('update:mode', $event)"
      />
      <a-space>
        <a-button
          size="small"
          :loading="approving"
          :disabled="polling"
          @click="$emit('approve')"
        >
          通过
        </a-button>
        <a-button
          size="small"
          :disabled="polling"
          @click="$emit('open-feedback')"
        >
          反馈重写
        </a-button>
        <a-button
          v-if="mode === 'edit'"
          size="small"
          :loading="savingSection"
          :disabled="!hasEditDraft"
          @click="$emit('save')"
        >
          保存
        </a-button>
        <a-button
          v-if="mode === 'edit'"
          size="small"
          @click="$emit('reset')"
        >
          重置
        </a-button>
      </a-space>
    </div>

    <!-- 章节内容卡片 -->
    <a-card class="review-content__card">
      <template #title>
        <div class="review-content__title">
          <span>章节 {{ activeChapter }}{{ activeChapterTitle ? ` ${activeChapterTitle}` : '' }}</span>
          <a-tag color="geekblue">
            提交人：{{ submitter }}
          </a-tag>
        </div>
      </template>

      <!-- 废标风险提示 -->
      <a-alert
        v-if="risks.length > 0"
        type="error"
        show-icon
        class="review-content__risk"
        :message="riskMessage"
      >
        <template #description>
          <div
            v-for="(risk, index) in risks"
            :key="index"
          >
            {{ risk.clause_no }} {{ risk.title }} — {{ risk.recommendation }}
          </div>
        </template>
      </a-alert>

      <!-- 编辑/预览 -->
      <a-textarea
        v-if="mode === 'edit'"
        :value="editContent"
        :rows="18"
        class="review-content__editor"
        @update:value="$emit('update:editContent', $event)"
      />
      <MarkdownRenderer
        v-else
        :source="displayContent"
        :project-id="projectId"
      />

      <!-- 批注区 -->
      <a-collapse
        :active-key="annotationPanelKeys"
        class="review-content__annotations"
        @change="onAnnotationPanelChange"
      >
        <a-collapse-panel
          :key="activeChapter"
          :header="`批注（${annotationCount}）`"
        >
          <a-spin :spinning="annotationsLoading">
            <a-empty
              v-if="annotations.length === 0"
              description="暂无批注"
            />
            <div
              v-else
              class="review-content__annotation-list"
            >
              <div
                v-for="item in annotations"
                :key="item.id"
                class="review-content__annotation-item"
              >
                <div class="review-content__annotation-header">
                  <span class="review-content__annotation-author">{{ item.created_by_name || '未知用户' }}</span>
                  <span class="review-content__annotation-time">{{ formatTime(item.created_at) }}</span>
                  <a-space
                    v-if="canManageAnnotation(item)"
                    size="small"
                  >
                    <a-button
                      size="small"
                      type="link"
                      @click="$emit('edit-annotation', item)"
                    >
                      编辑
                    </a-button>
                    <a-popconfirm
                      title="确认删除该条批注？"
                      ok-text="删除"
                      cancel-text="取消"
                      @confirm="$emit('delete-annotation', item.id)"
                    >
                      <a-button
                        size="small"
                        type="link"
                        danger
                      >
                        删除
                      </a-button>
                    </a-popconfirm>
                  </a-space>
                </div>
                <a-typography-paragraph :content="item.content" />
              </div>
            </div>
            <div class="review-content__annotation-add">
              <a-textarea
                :value="newAnnotation"
                :rows="2"
                :maxlength="2000"
                placeholder="输入批注内容（1-2000 字）"
                @update:value="$emit('update:newAnnotation', $event)"
              />
              <a-button
                size="small"
                :loading="addingAnnotation"
                :disabled="!newAnnotation.trim()"
                @click="$emit('add-annotation')"
              >
                添加批注
              </a-button>
            </div>
          </a-spin>
        </a-collapse-panel>
      </a-collapse>
    </a-card>

    <div class="review-content__hint">
      <InfoCircleOutlined /> 编辑保存后写入正式方案内容；或提交「反馈重写」触发 AI 重写
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { InfoCircleOutlined } from '@ant-design/icons-vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

interface AnnotationItem {
  id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string
}

interface RiskItem {
  clause_no: string
  title: string
  recommendation: string
}

const props = defineProps<{
  activeChapter: string
  activeChapterTitle: string
  submitter: string
  mode: 'edit' | 'preview'
  editContent: string
  displayContent: string
  hasEditDraft: boolean
  savingSection: boolean
  approving: boolean
  polling: boolean
  risks: RiskItem[]
  annotations: AnnotationItem[]
  annotationsLoading: boolean
  annotationCount: number
  newAnnotation: string
  addingAnnotation: boolean
  projectId: string
  isOwner: boolean
  currentUserId: string
}>()

const emit = defineEmits<{
  (e: 'update:mode', value: 'edit' | 'preview'): void
  (e: 'approve'): void
  (e: 'open-feedback'): void
  (e: 'save'): void
  (e: 'reset'): void
  (e: 'update:editContent', value: string): void
  (e: 'update:newAnnotation', value: string): void
  (e: 'add-annotation'): void
  (e: 'edit-annotation', item: AnnotationItem): void
  (e: 'delete-annotation', id: string): void
  (e: 'load-annotations', chapterNo: string): void
}>()

const modeOptions = [
  { label: '预览', value: 'preview' },
  { label: '编辑', value: 'edit' },
]

const annotationPanelKeys = ref<string[]>([])

const riskMessage = computed(() => {
  const hits = props.risks
  if (hits.length === 0) return ''
  return hits.length > 1 ? `废标风险：${hits[0].title} 等 ${hits.length} 条` : `废标风险：${hits[0].title}`
})

const canManageAnnotation = (item: AnnotationItem): boolean =>
  item.created_by === props.currentUserId || props.isOwner

const formatTime = (iso: string): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false })
}

const onAnnotationPanelChange = (keys: any) => {
  const active = Array.isArray(keys) ? keys : [keys]
  annotationPanelKeys.value = active
  for (const no of active) {
    if (no) emit('load-annotations', no)
  }
}
</script>

<style scoped>
.review-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.review-content__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 12px;
}

.review-content__card {
  background: var(--bg-surface);
  min-height: 360px;
}

.review-content__title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.review-content__risk {
  margin-bottom: 12px;
}

.review-content__editor {
  font-family: 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 13px;
  line-height: 1.7;
}

.review-content__annotations {
  margin-top: 16px;
}

.review-content__annotation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-content__annotation-item {
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface-hover);
}

.review-content__annotation-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.review-content__annotation-author {
  font-size: 13px;
  font-weight: 600;
}

.review-content__annotation-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.review-content__annotation-add {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.review-content__hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
