<template>
  <div class="review-view">
    <PageContainer
      title="审阅与导出"
      subtitle="审阅生成内容，批注修改意见或确认导出"
    >
      <LoadingSkeleton
        v-if="loading"
        :rows="6"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchStatus"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <EmptyState
        v-else-if="chapterKeys.length === 0"
        description="暂无章节内容，请先在「方案大纲生成」页生成技术方案"
      />

      <template v-else>
        <!-- 顶部：审阅进度条 + 全局操作 -->
        <div class="review-view__topbar">
          <ReviewProgressBar
            :total="chapterKeys.length"
            :approved="approvedCount"
            :rejected="rejectedCount"
            :annotated="annotatedCount"
          />
          <div class="review-view__topbar-actions">
            <a-button @click="goToGenerate">
              返回修改
            </a-button>
            <a-button
              type="primary"
              :loading="exportStatus === 'exporting'"
              @click="handleExport"
            >
              <template #icon>
                <DownloadOutlined />
              </template>
              导出 Word
            </a-button>
          </div>
        </div>

        <!-- 三栏布局 -->
        <div class="review-view__three-col">
          <!-- 左侧：章节导航 -->
          <div class="review-view__sider">
            <ReviewChapterList
              :outline="outline"
              :chapters="chapters"
              :active-chapter="activeChapter"
              :expanded-keys="expandedKeys"
              :review-feedback="reviewFeedback"
              :annotation-counts="annotationCounts"
              :chapter-statuses="chapterStatuses"
              @select="selectChapter"
              @expand="expandedKeys = $event"
            />
          </div>

          <!-- 中间：富文本预览区 -->
          <div class="review-view__content">
            <!-- 章节头部 -->
            <div class="review-view__content-header">
              <div class="review-view__content-title">
                <template v-if="viewMode === 'single'">
                  <span class="review-view__chapter-no">{{ activeChapter }}</span>
                  <span class="review-view__chapter-title">{{ activeChapterTitle }}</span>
                  <a-tag color="geekblue">
                    提交人：{{ submitterOf(activeChapter) }}
                  </a-tag>
                  <a-tag :color="currentStatusColor">
                    {{ currentStatusText }}
                  </a-tag>
                </template>
                <template v-else>
                  <span class="review-view__chapter-title">全文预览（{{ chapterKeys.length }} 章）</span>
                </template>
              </div>
              <a-radio-group
                v-model:value="viewMode"
                size="small"
                button-style="solid"
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
                  ref="wordEditorRef"
                  :content="currentHtml"
                  :readonly="true"
                  :annotations="annotationMarks"
                  :active-annotation-id="activeAnnotationId"
                  class="review-view__editor"
                  @selection-change="onSelectionChange"
                />
                <div v-else class="review-view__empty-content">
                  暂无内容
                </div>
              </div>
            </a-spin>

            <!-- 全文预览模式 -->
            <div v-else class="review-view__full-content" ref="fullContentRef">
              <div
                v-for="chapterNo in chapterKeys"
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
                <div class="review-view__paper-wrapper">
                  <WordEditor
                    v-if="chapterHtmlMap[chapterNo]"
                    :content="chapterHtmlMap[chapterNo]"
                    :readonly="true"
                    class="review-view__editor"
                  />
                  <div v-else class="review-view__empty-content">
                    暂无内容
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：审阅工作台 -->
          <div class="review-view__aside">
            <a-tabs
              v-model:activeKey="rightTab"
              class="review-view__aside-tabs"
            >
              <!-- Tab 1：审阅 -->
              <a-tab-pane key="action">
                <template #tab>
                  <span>
                    <AuditOutlined /> 审阅
                  </span>
                </template>
                <ReviewActionPanel
                  :active-chapter="activeChapter"
                  :current-status="currentChapterStatus"
                  :submitter="submitterOf(activeChapter)"
                  :approving="approving"
                  :polling="polling"
                  @approve="handleApprove"
                  @reject="handleReject"
                />
              </a-tab-pane>

              <!-- Tab 2：批注 -->
              <a-tab-pane key="annotation">
                <template #tab>
                  <span>
                    <CommentOutlined /> 批注
                    <a-badge
                      v-if="openAnnotationCount > 0"
                      :count="openAnnotationCount"
                      :number-style="{ backgroundColor: '#fa8c16' }"
                    />
                  </span>
                </template>
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
                      v-model:value="newAnnotation"
                      :placeholder="currentSelectionText ? '对选中文字添加批注...' : '添加批注（可先在正文中选中文字）...'"
                      :disabled="addingAnnotation"
                      @press-enter="addAnnotation(activeChapter)"
                    >
                      <template #addonAfter>
                        <a-button
                          type="primary"
                          :loading="addingAnnotation"
                          @click="addAnnotation(activeChapter)"
                        >
                          添加
                        </a-button>
                      </template>
                    </a-input>
                  </div>
                  <!-- 筛选 -->
                  <div class="review-view__annotation-filter">
                    <a-radio-group
                      v-model:value="annotationFilter"
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
                        @click="locateAnnotation(item)"
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
                              @click.stop="toggleAnnotationStatus(activeChapter, item.id)"
                            >
                              {{ item.status === 'resolved' ? '重新打开' : '标记解决' }}
                            </a-button>
                            <a-button
                              v-if="item.created_by === currentUserId"
                              type="link"
                              size="small"
                              danger
                              @click.stop="deleteAnnotation(activeChapter, item.id)"
                            >
                              删除
                            </a-button>
                          </span>
                        </div>
                      </div>
                    </div>
                  </a-spin>
                </div>
              </a-tab-pane>

              <!-- Tab 3：版本 -->
              <a-tab-pane key="version">
                <template #tab>
                  <span>
                    <HistoryOutlined /> 版本
                  </span>
                </template>
                <div class="review-view__version-panel">
                  <a-tabs v-model:activeKey="versionSubTab" size="small">
                    <a-tab-pane key="list" tab="版本列表">
                      <ReviewVersionSection
                        ref="versionSectionRef"
                        :project-id="projectId"
                        @rolled-back="handleRolledBack"
                      />
                    </a-tab-pane>
                    <a-tab-pane key="compare" tab="差异比对">
                      <ReviewVersionCompare
                        ref="versionCompareRef"
                        :project-id="projectId"
                        :versions="versionList"
                        :current-content="currentChapterMarkdown"
                      />
                    </a-tab-pane>
                  </a-tabs>
                </div>
              </a-tab-pane>
            </a-tabs>
          </div>
        </div>

        <!-- 导出结果已移至弹窗 -->
      </template>
    </PageContainer>

    <!-- 批注编辑弹窗 -->
    <AnnotationEditModal
      ref="annotationEditRef"
      :project-id="projectId"
      :active-chapter="activeChapter"
      @updated="(id, patch) => mergeUpdatedAnnotation(activeChapter, id, patch)"
    />

    <!-- 导出选项弹窗 -->
    <ReviewExportModal
      v-model:visible="exportModalVisible"
      :project-id="projectId"
      @exported="handleExported"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { message, Empty } from 'ant-design-vue'
import {
  DownloadOutlined,
  AuditOutlined,
  CommentOutlined,
  HistoryOutlined,
} from '@ant-design/icons-vue'
import type { AnnotationItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import WordEditor from '@/components/editor/WordEditor.vue'
import ReviewChapterList from './components/ReviewChapterList.vue'
import ReviewProgressBar from './components/ReviewProgressBar.vue'
import ReviewActionPanel from './components/ReviewActionPanel.vue'
import ReviewVersionSection from './components/ReviewVersionSection.vue'
import ReviewVersionCompare from './components/ReviewVersionCompare.vue'
import ReviewExportModal from './components/ReviewExportModal.vue'
import AnnotationEditModal from './components/AnnotationEditModal.vue'
import { useAnnotations } from './composables/useAnnotations'
import { useReviewState } from './composables/useReviewState'
import { useReviewNavigation } from './composables/useReviewNavigation'
import { useReviewActions } from './composables/useReviewActions'

const route = useRoute()
const projectId = route.params.projectId as string

/* ==================== 状态层（按依赖顺序初始化） ==================== */

// 1. 基础状态
const {
  loading,
  loadError,
  chapters,
  outline,
  reviewFeedback,
  exportStatus,
  exportStorageKey,
  disqualificationRisks,
  polling,
  fetchStatus,
  applyStatus,
  pollUntil,
  stopPolling,
  fetchSubmitters,
  fetchDisqualificationRisks,
  chapterKeys,
  chapterStatuses,
  approvedCount,
  rejectedCount,
  submitterOf,
} = useReviewState(projectId)

// 2. 批注
const {
  annotationsLoading,
  newAnnotation,
  addingAnnotation,
  currentSelection,
  annotationListOf,
  annotationCountOf,
  loadAnnotations,
  addAnnotation,
  deleteAnnotation,
  toggleAnnotationStatus,
  mergeUpdatedAnnotation,
  setSelection,
} = useAnnotations(projectId)

// 3. 导航（依赖 state + annotations）
const {
  activeChapter,
  expandedKeys,
  chapterHtmlMap,
  contentLoading,
  viewMode,
  fullContentRef,
  activeChapterTitle,
  activeChapterRisks,
  currentHtml,
  currentChapterMarkdown,
  selectChapter,
  loadChapterHtml,
  clearHtmlCache,
  stopFullObserver,
} = useReviewNavigation({
  projectId,
  getChapters: () => chapters.value,
  getOutline: () => outline.value,
  getRisks: () => disqualificationRisks.value,
  loadAnnotations,
})

// 4. 操作（依赖 state + navigation）
const {
  approving,
  exportModalVisible,
  handleApprove,
  handleReject,
  handleExport,
  handleExported,
  goToGenerate,
} = useReviewActions({
  projectId,
  getActiveChapter: () => activeChapter.value,
  getReviewFeedback: () => reviewFeedback.value,
  setReviewFeedback: (v) => { reviewFeedback.value = v },
  setExportStatus: (v) => { exportStatus.value = v },
  setExportStorageKey: (v) => { exportStorageKey.value = v },
  pollUntil,
})

/* ==================== UI 状态 ==================== */
const rightTab = ref<'action' | 'annotation' | 'version'>('action')
const annotationFilter = ref<'open' | 'resolved' | 'all'>('open')
const activeAnnotationId = ref<string | null>(null)
const wordEditorRef = ref<InstanceType<typeof WordEditor> | null>(null)
const versionSubTab = ref<'list' | 'compare'>('list')
const versionCompareRef = ref<InstanceType<typeof ReviewVersionCompare> | null>(null)
const versionSectionRef = ref<InstanceType<typeof ReviewVersionSection> | null>(null)
const annotationEditRef = ref<InstanceType<typeof AnnotationEditModal> | null>(null)

/* ==================== 计算属性 ==================== */
const versionList = computed(() => versionSectionRef.value?.versions || [])

const currentChapterStatus = computed(() => chapterStatuses.value[activeChapter.value] || 'pending')
const currentStatusText = computed(() => {
  const map: Record<string, string> = { pending: '未审阅', approved: '已通过', rejected: '需修改' }
  return map[currentChapterStatus.value] || '未审阅'
})
const currentStatusColor = computed(() => {
  const map: Record<string, string> = { pending: 'default', approved: 'green', rejected: 'orange' }
  return map[currentChapterStatus.value] || 'default'
})

const annotationCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {}
  chapterKeys.value.forEach((no) => { counts[no] = annotationCountOf(no) })
  return counts
})

const annotatedCount = computed(
  () => chapterKeys.value.filter((no) => annotationCountOf(no) > 0).length,
)

const currentAnnotations = computed(() => annotationListOf(activeChapter.value))
const openAnnotationCount = computed(
  () => currentAnnotations.value.filter((a) => a.status !== 'resolved').length,
)
const resolvedAnnotationCount = computed(
  () => currentAnnotations.value.filter((a) => a.status === 'resolved').length,
)

const filteredAnnotations = computed(() => {
  if (annotationFilter.value === 'all') return currentAnnotations.value
  return currentAnnotations.value.filter((a) =>
    annotationFilter.value === 'open' ? a.status !== 'resolved' : a.status === 'resolved',
  )
})

const annotationMarks = computed(() =>
  currentAnnotations.value
    .filter((a) => a.selection && a.selection.from != null && a.selection.to != null)
    .map((a) => ({
      id: a.id,
      from: a.selection!.from,
      to: a.selection!.to,
      status: a.status,
    })),
)

const currentSelectionText = computed(() => currentSelection.value?.text || '')

/* ==================== 方法 ==================== */
const onSelectionChange = (sel: { from: number; to: number; text: string } | null) => {
  setSelection(sel)
}

const locateAnnotation = (item: AnnotationItem) => {
  activeAnnotationId.value = item.id
  if (item.selection && wordEditorRef.value) {
    wordEditorRef.value.scrollToPosition(item.selection.from)
  }
  setTimeout(() => {
    if (activeAnnotationId.value === item.id) activeAnnotationId.value = null
  }, 3000)
}

const formatTime = (time: string): string => {
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

const handleRolledBack = async (restored: number) => {
  const data = await fetchStatus()
  if (data) {
    applyStatus(
      data,
      () => activeChapter.value,
      (v) => { activeChapter.value = v },
      () => expandedKeys.value,
      (v) => { expandedKeys.value = v },
      () => route.query.chapter as string,
    )
    clearHtmlCache()
  }
  message.success(`回滚成功，已恢复 ${restored} 个章节内容`)
  if (activeChapter.value) await loadChapterHtml(activeChapter.value)
}

/* ==================== 生命周期 ==================== */
onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchStatus()
    if (data) {
      applyStatus(
        data,
        () => activeChapter.value,
        (v) => { activeChapter.value = v },
        () => expandedKeys.value,
        (v) => { expandedKeys.value = v },
        () => route.query.chapter as string,
      )
    }
    await fetchSubmitters()
    await versionSectionRef.value?.load()
    await fetchDisqualificationRisks()
    if (activeChapter.value) {
      await loadChapterHtml(activeChapter.value)
      loadAnnotations(activeChapter.value)
    }
  } catch { loadError.value = '审阅状态加载失败' }
  finally { loading.value = false }
})

onUnmounted(() => {
  stopPolling()
  stopFullObserver()
})
</script>

<style scoped>
.review-view__topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.review-view__topbar :deep(.review-progress) {
  flex: 1;
  margin-bottom: 0;
}

.review-view__topbar-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* 三栏布局 */
.review-view__three-col {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.review-view__sider {
  width: 280px;
  flex-shrink: 0;
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
}

.review-view__content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-view__aside {
  width: 340px;
  flex-shrink: 0;
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 100px);
  background: var(--bg-elevated, #1f1f1f);
  border: 1px solid var(--border-color, #303030);
  border-radius: 8px;
  overflow: hidden;
}

.review-view__aside-tabs {
  height: 100%;
}

.review-view__aside-tabs :deep(.ant-tabs-content-holder) {
  max-height: calc(100vh - 160px);
  overflow-y: auto;
}

/* 章节头部 */
.review-view__content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-elevated, #1f1f1f);
  border: 1px solid var(--border-color, #303030);
  border-radius: 8px;
}

.review-view__content-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.review-view__chapter-no {
  font-size: 14px;
  font-weight: 600;
  color: var(--primary-color, #1890ff);
}

.review-view__chapter-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

/* 废标风险 */
.review-view__risk-alert {
  flex-shrink: 0;
}

.review-view__risk-item {
  font-size: 12px;
  line-height: 1.8;
}

/* 富文本预览区 */
.review-view__paper-wrapper {
  background: var(--bg-surface, #141414);
  border: 1px solid var(--border-color, #303030);
  border-radius: 8px;
  padding: 24px;
  min-height: 500px;
  display: flex;
  justify-content: center;
}

.review-view__editor {
  width: 100%;
  max-width: 210mm;
}

.review-view__editor :deep(.ProseMirror) {
  background: #fff;
  color: #333;
  padding: 25.4mm;
  min-height: 297mm;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  border-radius: 4px;
}

.review-view__empty-content {
  color: var(--text-secondary, #999);
  padding: 60px 0;
}

/* 批注面板 */
.review-view__annotation-panel {
  padding: 12px;
}

.review-view__selection-hint {
  padding: 6px 10px;
  margin-bottom: 8px;
  background: rgba(24, 144, 255, 0.1);
  border: 1px solid rgba(24, 144, 255, 0.3);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.4;
}

.review-view__selection-label {
  color: var(--text-secondary, #999);
}

.review-view__selection-text {
  color: var(--primary-color, #1890ff);
  font-style: italic;
}

.review-view__annotation-filter {
  margin-bottom: 10px;
}

.review-view__annotation-actions {
  margin-bottom: 10px;
}

.review-view__annotation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.review-view__annotation-item {
  padding: 10px 12px;
  background: var(--bg-surface, #2a2a2a);
  border-radius: 6px;
  border-left: 3px solid #fa8c16;
  cursor: pointer;
  transition: all 0.2s;
}

.review-view__annotation-item:hover {
  background: var(--bg-hover, #333);
}

.review-view__annotation-item--active {
  border-left-color: #1890ff;
  box-shadow: 0 0 0 1px rgba(24, 144, 255, 0.3);
}

.review-view__annotation-item--resolved {
  border-left-color: #52c41a;
  opacity: 0.75;
}

.review-view__annotation-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.review-view__annotation-status {
  font-size: 10px;
  margin: 0;
}

.review-view__annotation-quote {
  font-size: 11px;
  color: var(--text-tertiary, #888);
  font-style: italic;
  padding: 4px 8px;
  margin-bottom: 6px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 3px;
  border-left: 2px solid var(--border-color, #444);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-view__annotation-author {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.review-view__annotation-time {
  font-size: 11px;
  color: var(--text-tertiary, #666);
}

.review-view__annotation-content {
  font-size: 13px;
  color: var(--text-secondary, #ccc);
  line-height: 1.5;
}

.review-view__annotation-footer {
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.review-view__annotation-btns {
  display: flex;
  gap: 0;
}

.review-view__version-panel {
  max-height: 500px;
  overflow-y: auto;
}

/* 全文预览模式 */
.review-view__full-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.review-view__full-chapter {
  scroll-margin-top: 16px;
}

.review-view__full-chapter-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  margin-bottom: 8px;
  background: var(--bg-elevated, #1f1f1f);
  border: 1px solid var(--border-color, #303030);
  border-radius: 6px;
}

.review-view__full-chapter-no {
  font-size: 14px;
  font-weight: 600;
  color: var(--primary-color, #1890ff);
}

.review-view__full-chapter-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

/* 窄屏适配 */
@media (max-width: 1400px) {
  .review-view__aside {
    width: 300px;
  }
}

@media (max-width: 1200px) {
  .review-view__three-col {
    flex-direction: column;
  }
  .review-view__sider,
  .review-view__aside {
    width: 100%;
    position: static;
    max-height: none;
  }
}
</style>
