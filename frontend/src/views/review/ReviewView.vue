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
        v-else-if="!hasDivision && chapterKeys.length === 0"
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
              :disabled="hasDivision && !exportAvailable"
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
              :mode="hasDivision ? 'division' : 'chapter'"
              :unit-keys="hasDivision ? chapterKeys : undefined"
              :raw-statuses="rawStatusMap"
              @select="selectChapter"
              @expand="expandedKeys = $event"
            />
          </div>

          <!-- 中间：富文本预览区 -->
          <ReviewContentArea
            ref="contentAreaRef"
            :view-mode="viewMode"
            :active-chapter="activeChapter"
            :active-chapter-title="activeChapterTitle"
            :submitter="submitterOf(activeChapter)"
            :current-status-color="currentStatusColor"
            :current-status-text="currentStatusText"
            :has-division="hasDivision"
            :full-keys="fullKeys"
            :active-chapter-risks="activeChapterRisks"
            :content-loading="contentLoading"
            :current-html="currentHtml"
            :annotation-marks="annotationMarks"
            :active-annotation-id="activeAnnotationId"
            :outline="outline"
            :chapter-html-map="chapterHtmlMap"
            @view-mode-change="onViewModeChange"
            @selection-change="onSelectionChange"
            @full-content-mounted="(el) => fullContentRef = el"
          />

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
                <ReviewAutoComments
                  :comments="reviewComments"
                  :titles="chapterTitleMap"
                  @locate="locateAutoComment"
                />
                <ReviewActionPanel
                  :active-chapter="activeChapter"
                  :current-status="currentChapterStatus"
                  :submitter="submitterOf(activeChapter)"
                  :approving="approving"
                  :polling="polling"
                  :raw-status="currentRawStatus || undefined"
                  :enable-approve="hasDivision ? divisionReviewable : true"
                  :enable-reject="hasDivision ? divisionReviewable : true"
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
                <ReviewAnnotationPanel
                  v-model:new-annotation="newAnnotation"
                  v-model:annotation-filter="annotationFilter"
                  :current-selection-text="currentSelectionText"
                  :adding-annotation="addingAnnotation"
                  :annotations-loading="annotationsLoading"
                  :filtered-annotations="filteredAnnotations"
                  :open-annotation-count="openAnnotationCount"
                  :resolved-annotation-count="resolvedAnnotationCount"
                  :active-annotation-id="activeAnnotationId"
                  :active-chapter="activeChapter"
                  @add="addAnnotation"
                  @locate="locateAnnotation"
                  @toggle="toggleAnnotationStatus"
                  @delete="deleteAnnotation"
                />
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
      :current-chapter="activeChapter"
      @exported="handleExported"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  DownloadOutlined,
  AuditOutlined,
  CommentOutlined,
  HistoryOutlined,
} from '@ant-design/icons-vue'
import type { AnnotationItem } from '@/types'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ReviewChapterList from './components/ReviewChapterList.vue'
import ReviewProgressBar from './components/ReviewProgressBar.vue'
import ReviewActionPanel from './components/ReviewActionPanel.vue'
import ReviewAutoComments from './components/ReviewAutoComments.vue'
import ReviewVersionSection from './components/ReviewVersionSection.vue'
import ReviewVersionCompare from './components/ReviewVersionCompare.vue'
import ReviewExportModal from './components/ReviewExportModal.vue'
import ReviewAnnotationPanel from './components/ReviewAnnotationPanel.vue'
import ReviewContentArea from './components/ReviewContentArea.vue'
import AnnotationEditModal from './components/AnnotationEditModal.vue'
import { useAnnotations } from './composables/useAnnotations'
import { useAnnotationView } from './composables/useAnnotationView'
import { useReviewState } from './composables/useReviewState'
import { useReviewNavigation } from './composables/useReviewNavigation'
import { useReviewActions } from './composables/useReviewActions'
import { useReviewStatusDisplay } from './composables/useReviewStatusDisplay'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

/* ==================== 状态层（按依赖顺序初始化） ==================== */

// 1. 基础状态
const {
  loading,
  loadError,
  chapters,
  outline,
  reviewFeedback,
  reviewComments,
  exportStatus,
  exportStorageKey,
  disqualificationRisks,
  polling,
  fetchStatus,
  applyStatus,
  pollUntil,
  stopPolling,
  fetchAssignments,
  fetchSubmitters,
  fetchDisqualificationRisks,
  chapterKeys,
  formalChapterKeys,
  hasDivision,
  rawStatusOf,
  assignmentIdOf,
  titleOf,
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
  getTitle: titleOf,
  getFullKeys: () => fullKeys.value,
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
  getAssignmentId: () => assignmentIdOf(activeChapter.value),
  refreshDivisionData: refreshAll,
})

/* ==================== UI 状态 ==================== */
const rightTab = ref<'action' | 'annotation' | 'version'>('action')
const annotationFilter = ref<'open' | 'resolved' | 'all'>('open')
const activeAnnotationId = ref<string | null>(null)
const contentAreaRef = ref<InstanceType<typeof ReviewContentArea> | null>(null)
const versionSubTab = ref<'list' | 'compare'>('list')
const versionCompareRef = ref<InstanceType<typeof ReviewVersionCompare> | null>(null)
const versionSectionRef = ref<InstanceType<typeof ReviewVersionSection> | null>(null)
const annotationEditRef = ref<InstanceType<typeof AnnotationEditModal> | null>(null)

/* ==================== 计算属性 ==================== */
const versionList = computed(() => versionSectionRef.value?.versions || [])

const { currentChapterStatus, currentRawStatus, currentStatusText, currentStatusColor } =
  useReviewStatusDisplay({ hasDivision, chapterStatuses, rawStatusOf, activeChapter })

/** 分工模式下当前章节是否可执行审阅（仅 submitted 待审可操作） */
const divisionReviewable = computed(
  () => hasDivision.value && currentRawStatus.value === 'submitted',
)

/** 全文预览章节集合：分工模式 = 已回写的正式方案（章级）；AI 模式 = state.chapters */
const fullKeys = computed(() => (hasDivision.value ? formalChapterKeys.value : chapterKeys.value))
const fullAvailable = computed(() => fullKeys.value.length > 0)
/** 正式方案是否可导出（分工模式需至少一章已通过回写） */
const exportAvailable = computed(() => formalChapterKeys.value.length > 0)

/** 章节号 → 标题（AI 自动审阅意见卡片用；章级意见取大纲标题兜底） */
const chapterTitleMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const c of outline.value) map[c.chapter_no] = c.title
  for (const no of chapterKeys.value) {
    const t = titleOf(no)
    if (t) map[no] = t
  }
  return map
})

/** 分工原始状态表（树状态点配色用） */
const rawStatusMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const no of chapterKeys.value) map[no] = rawStatusOf(no) || 'pending'
  return map
})

/* ==================== 数据刷新（分工审阅动作/回滚后调用） ==================== */
function applyWithNav(data: Parameters<typeof applyStatus>[0]) {
  applyStatus(
    data,
    () => activeChapter.value,
    (v) => { activeChapter.value = v },
    () => expandedKeys.value,
    (v) => { expandedKeys.value = v },
    () => route.query.chapter as string,
  )
}

async function refreshAll() {
  const data = await fetchStatus()
  if (data) applyWithNav(data)
  await fetchAssignments()
  // 分工模式：fetchAssignments 就绪后审阅单元切换为分工章节，补齐 active 选中
  if (!activeChapter.value && chapterKeys.value.length > 0) {
    const q = route.query.chapter as string | undefined
    activeChapter.value = chapterKeys.value.includes(q || '') ? (q as string) : chapterKeys.value[0]
    router.replace({ query: { ...route.query, chapter: activeChapter.value } })
  }
  clearHtmlCache()
  if (activeChapter.value) {
    await loadChapterHtml(activeChapter.value)
    loadAnnotations(activeChapter.value)
  }
}

/* ==================== 批注视图模型（useAnnotationView） ==================== */
const {
  annotationCounts,
  annotatedCount,
  openAnnotationCount,
  resolvedAnnotationCount,
  filteredAnnotations,
  annotationMarks,
  currentSelectionText,
} = useAnnotationView({
  chapterKeys,
  getActiveChapter: () => activeChapter.value,
  getAnnotationCount: annotationCountOf,
  getAnnotations: annotationListOf,
  getSelectionText: () => currentSelection.value?.text || '',
  filter: annotationFilter,
})

/* ==================== 方法 ==================== */
const onSelectionChange = (sel: { from: number; to: number; text: string } | null) => {
  setSelection(sel)
}

/**
 * 定位 AI 自动审阅意见所指章节.
 *
 * 自动意见的 chapter_no 来自 state.chapters（**章级**）；分工模式下审阅单元是子节
 * （如 3.1）→ 章级意见按 `章号.` 前缀落到首个子节，避免点了没反应。
 */
const locateAutoComment = (chapterNo: string) => {
  const keys = chapterKeys.value
  const hit = keys.includes(chapterNo) ? chapterNo : keys.find((k) => k.startsWith(`${chapterNo}.`))
  if (!hit) {
    message.info(`章节 ${chapterNo} 不在当前审阅单元中，请在左侧章节树查看`)
    return
  }
  void selectChapter(hit)
}

/** 预览模式切换守卫：全文不可用（无已通过章节）时阻止并提示 */
const onViewModeChange = (e: { target: { value?: string } }) => {
  const v = e.target.value
  if (v === 'full' && !fullAvailable.value) {
    message.info(
      hasDivision.value
        ? '暂无已通过并回写的章节，章节审核通过后可切换全文预览'
        : '暂无章节内容，无法全文预览',
    )
    viewMode.value = 'single'
    return
  }
  viewMode.value = v as 'single' | 'full'
}

const locateAnnotation = (item: AnnotationItem) => {
  activeAnnotationId.value = item.id
  if (item.selection && contentAreaRef.value) {
    contentAreaRef.value.scrollToPosition(item.selection.from)
  }
  setTimeout(() => {
    if (activeAnnotationId.value === item.id) activeAnnotationId.value = null
  }, 3000)
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
    if (data) applyWithNav(data)
    // 分工数据就绪（分工模式审阅单元为子节）
    await fetchSubmitters()
    if (data && !activeChapter.value && chapterKeys.value.length > 0) {
      const q = route.query.chapter as string | undefined
      activeChapter.value = chapterKeys.value.includes(q || '') ? (q as string) : chapterKeys.value[0]
    }
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

<style scoped src="./review-view.css">
</style>
