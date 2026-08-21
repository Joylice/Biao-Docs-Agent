<template>
  <div class="review-view">
    <PageContainer
      title="审阅与导出"
      subtitle="审阅生成内容，提交修改意见或确认导出"
    >
      <a-alert
        v-if="rewriting"
        type="info"
        show-icon
        class="mb-4"
        message="章节重写中，请稍候，完成后将自动刷新审阅内容"
      />

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
        <!-- 左右分栏：章节列表 + 内容区 -->
        <div class="review-view__split">
          <div class="review-view__sider">
            <ReviewChapterList
              :outline="outline"
              :chapters="chapters"
              :active-chapter="activeChapter"
              :expanded-keys="expandedKeys"
              :review-feedback="reviewFeedback"
              :edit-drafts="editDrafts"
              @select="selectChapter"
              @expand="expandedKeys = $event"
            />
          </div>
          <div class="review-view__main">
            <ReviewContentPanel
              v-model:mode="mode"
              v-model:new-annotation="newAnnotation"
              :active-chapter="activeChapter"
              :active-chapter-title="activeChapterTitle"
              :submitter="submitterOf(activeChapter)"
              :edit-content="editDrafts[activeChapter] || ''"
              :display-content="displayContent"
              :has-edit-draft="hasEditDraft(activeChapter)"
              :saving-section="savingSection"
              :approving="approving"
              :polling="polling"
              :risks="activeChapterRisks"
              :annotations="annotationListOf(activeChapter)"
              :annotations-loading="annotationsLoading"
              :annotation-count="annotationCountOf(activeChapter)"
              :adding-annotation="addingAnnotation"
              :project-id="projectId"
              :is-owner="isOwner"
              :current-user-id="currentUserId"
              @approve="handleApprove"
              @open-feedback="feedbackRef?.open()"
              @save="handleSaveEditDraft"
              @reset="resetEditDraft"
              @update:edit-content="(val) => (editDrafts[activeChapter] = val)"
              @add-annotation="addAnnotation(activeChapter)"
              @edit-annotation="startEditAnnotation"
              @delete-annotation="(id) => deleteAnnotation(activeChapter, id)"
              @load-annotations="loadAnnotations"
            />
          </div>
        </div>

        <!-- 底部操作区 -->
        <div class="review-view__actions">
          <a-button @click="goToGenerate">
            返回修改
          </a-button>
          <a-button
            type="primary"
            :loading="exporting"
            size="large"
            @click="handleExport"
          >
            导出 Word 文档
          </a-button>
          <a-button
            :loading="approving"
            :disabled="polling"
            size="large"
            @click="handleApprove"
          >
            审阅通过
          </a-button>
        </div>

        <!-- 导出结果 -->
        <a-result
          v-if="exportStatus === 'done'"
          status="success"
          title="导出成功"
          sub-title="技术方案已生成，可下载编辑"
        >
          <template #extra>
            <a-button @click="handleDownload">
              下载文档
            </a-button>
          </template>
        </a-result>

        <!-- 版本库（面板 + 快照/归档弹窗 + 下载/回滚编排） -->
        <ReviewVersionSection
          ref="versionSectionRef"
          :project-id="projectId"
          @rolled-back="handleRolledBack"
        />
      </template>
    </PageContainer>

    <!-- 反馈重写抽屉 -->
    <FeedbackDrawer
      ref="feedbackRef"
      :project-id="projectId"
      :active-chapter="activeChapter"
      @rewrite="handleRewriteStarted"
    />

    <!-- 批注编辑弹窗 -->
    <AnnotationEditModal
      ref="annotationEditRef"
      :project-id="projectId"
      :active-chapter="activeChapter"
      @updated="(id, patch) => mergeUpdatedAnnotation(activeChapter, id, patch)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  saveWorkflowSection,
  fetchWorkflowStatus,
  fetchWorkflowExport,
  confirmReview,
  fetchChapterAssignments,
  fetchDisqualificationRisks as fetchDisqualificationRisksApi,
} from '@/api'
import type { WorkflowStatus, AnnotationItem } from '@/types'
import { currentUserId } from '@/stores/currentUser'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ReviewChapterList from './components/ReviewChapterList.vue'
import ReviewContentPanel from './components/ReviewContentPanel.vue'
import ReviewVersionSection from './components/ReviewVersionSection.vue'
import FeedbackDrawer from './components/FeedbackDrawer.vue'
import AnnotationEditModal from './components/AnnotationEditModal.vue'
import { useAnnotations } from './composables/useAnnotations'

interface OutlineNode { chapter_no: string; title: string; sections?: string[] }
interface RiskItem {
  clause_no: string
  title: string
  severity: string
  risk_category: string
  recommendation: string
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

// 状态
const loading = ref(false)
const loadError = ref('')
const chapters = ref<Record<string, string>>({})
const outline = ref<OutlineNode[]>([])
const submitters = ref<Record<string, string>>({})
const expandedKeys = ref<string[]>([])
const activeChapter = ref('')
const reviewFeedback = ref<Record<string, string>>({})
const approving = ref(false)
const exporting = ref(false)
const exportStatus = ref('')
const exportStorageKey = ref('')
const rewriting = ref(false)

// UI 状态
const mode = ref<'edit' | 'preview'>('preview')
const editDrafts = ref<Record<string, string>>({})

// 批注（懒加载/增删/合并下沉 useAnnotations）
const {
  annotationsLoading,
  newAnnotation,
  addingAnnotation,
  annotationListOf,
  annotationCountOf,
  loadAnnotations,
  addAnnotation,
  deleteAnnotation,
  mergeUpdatedAnnotation,
} = useAnnotations(projectId)

// 废标风险
const disqualificationRisks = ref<Record<string, RiskItem[]>>({})

const versionSectionRef = ref<InstanceType<typeof ReviewVersionSection> | null>(null)
/** 项目负责人标识：由版本域子组件 expose 透传 */
const isOwner = computed(() => versionSectionRef.value?.isOwner ?? false)
const feedbackRef = ref<InstanceType<typeof FeedbackDrawer> | null>(null)
const annotationEditRef = ref<InstanceType<typeof AnnotationEditModal> | null>(null)

const chapterKeys = computed(() => Object.keys(chapters.value))
const polling = computed(() => pollTimer !== null)
const activeChapterTitle = computed(
  () => outline.value.find((c) => c.chapter_no === activeChapter.value)?.title || '',
)
const activeChapterRisks = computed<RiskItem[]>(
  () => disqualificationRisks.value[activeChapter.value] || [],
)
const displayContent = computed(
  () => editDrafts.value[activeChapter.value] ?? chapters.value[activeChapter.value] ?? '',
)

const submitterOf = (chapterNo: string): string => submitters.value[chapterNo] || 'AI 生成/未分配'

const hasEditDraft = (chapterNo: string): boolean => {
  const draft = editDrafts.value[chapterNo]
  return draft !== undefined && draft !== chapters.value[chapterNo]
}

const selectChapter = (chapterNo: string) => {
  activeChapter.value = chapterNo
  if (editDrafts.value[chapterNo] === undefined) {
    editDrafts.value[chapterNo] = chapters.value[chapterNo] || ''
  }
}

const resetEditDraft = () => {
  editDrafts.value[activeChapter.value] = chapters.value[activeChapter.value] || ''
}

const savingSection = ref(false)

const handleSaveEditDraft = async () => {
  const no = activeChapter.value
  const content = editDrafts.value[no]?.trim() ?? ''
  if (!no || !content) { message.warning('章节内容不能为空'); return }
  if (savingSection.value) return
  savingSection.value = true
  try {
    await saveWorkflowSection(projectId, no, content)
    chapters.value[no] = content
    delete editDrafts.value[no]
    message.success(`章节 ${no} 已保存到正式方案`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '章节保存失败')
  } finally { savingSection.value = false }
}

// 轮询
const startEditAnnotation = (item: AnnotationItem) => {
  annotationEditRef.value?.open(item)
}

let pollTimer: number | null = null
const stopPolling = () => { if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null } }

const applyStatus = (data: WorkflowStatus) => {
  chapters.value = data.chapters || {}
  outline.value = (data.outline || []) as OutlineNode[]
  reviewFeedback.value = data.review_feedback || {}
  exportStatus.value = data.export_status || ''
  exportStorageKey.value = data.export_storage_key || ''
  if (!activeChapter.value) {
    const keys = Object.keys(chapters.value)
    if (keys.length > 0) activeChapter.value = keys[0]
  }
  for (const chapterNo of Object.keys(chapters.value)) {
    if (editDrafts.value[chapterNo] === undefined) {
      editDrafts.value[chapterNo] = chapters.value[chapterNo] || ''
    }
  }
  if (expandedKeys.value.length === 0) {
    expandedKeys.value = outline.value.map((c) => c.chapter_no)
  }
}

const fetchStatus = async (): Promise<WorkflowStatus | undefined> => {
  const res = await fetchWorkflowStatus(projectId)
  return res.data?.data
}

const fetchSubmitters = async () => {
  try {
    const res = await fetchChapterAssignments(projectId)
    const items = (res.data?.data?.items || []) as { chapter_no: string; submitted_by_name?: string }[]
    const map: Record<string, string> = {}
    for (const it of items) { if (it.submitted_by_name) map[it.chapter_no] = it.submitted_by_name }
    submitters.value = map
  } catch { /* 降级 */ }
}

const fetchDisqualificationRisks = async () => {
  try {
    const res = await fetchDisqualificationRisksApi(projectId)
    disqualificationRisks.value = res.data?.data?.risks || {}
  } catch { disqualificationRisks.value = {} }
}

/** 版本回滚成功：按原时序刷新工作流状态并清空编辑草稿 */
const handleRolledBack = async (restored: number) => {
  const data = await fetchStatus()
  if (data) { applyStatus(data); editDrafts.value = {} }
  message.success(`回滚成功，已恢复 ${restored} 个章节内容`)
}

const pollUntil = (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => {
  stopPolling()
  let attempts = 0
  pollTimer = window.setInterval(async () => {
    attempts += 1
    try {
      const data = await fetchStatus()
      if (!data) return
      applyStatus(data)
      if (data.error) { stopPolling(); rewriting.value = false; message.error(data.error); return }
      if (until(data)) { stopPolling(); onDone?.(data) }
      else if (attempts >= 90) { stopPolling(); rewriting.value = false; message.warning('等待超时，请稍后手动刷新') }
    } catch { /* 重试 */ }
  }, 2000)
}

const handleApprove = async () => {
  approving.value = true
  try {
    const res = await confirmReview(projectId, { action: 'approved' })
    if (res.data?.code !== 0) { message.error(res.data?.message || '审阅确认失败'); return }
    message.success('审阅通过，正在生成导出文档...')
    pollUntil((data) => data.export_status === 'done', () => message.success('导出完成，可下载文档'))
  } catch { message.error('审阅确认失败') }
  finally { approving.value = false }
}

/** 反馈抽屉提交成功并触发 AI 重写：进入轮询等待重写完成 */
const handleRewriteStarted = () => {
  rewriting.value = true
  let sawCleared = false
  pollUntil(
    (data) => { if (!data.interrupt) sawCleared = true; return sawCleared && data.interrupt?.type === 'review_request' },
    () => {
      rewriting.value = false
      if (editDrafts.value[activeChapter.value] !== undefined) {
        editDrafts.value[activeChapter.value] = chapters.value[activeChapter.value] || ''
      }
      message.success('章节重写完成，请重新审阅')
    },
  )
}

const handleExport = async () => {
  exporting.value = true
  try {
    const res = await fetchWorkflowExport(projectId)
    const data = res.data?.data
    exportStatus.value = data?.export_status || 'pending'
    exportStorageKey.value = data?.export_storage_key || ''
    if (exportStatus.value === 'done') message.success('导出成功')
  } catch { message.error('导出失败') }
  finally { exporting.value = false }
}

const handleDownload = () => {
  if (!exportStorageKey.value) { message.info('文档尚未就绪，请先完成导出'); return }
  message.success(`文档已就绪（存储标识：${exportStorageKey.value}）`)
}

const goToGenerate = () => router.push({ name: 'Generate', params: { projectId } })

onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchStatus()
    if (data) applyStatus(data)
    await fetchSubmitters()
    await versionSectionRef.value?.load()
    await fetchDisqualificationRisks()
  } catch { loadError.value = '审阅状态加载失败' }
  finally { loading.value = false }
})

onUnmounted(() => stopPolling())
</script>

<style scoped>
.review-view { width: 100%; }
.mb-4 { margin-bottom: 16px; }

.review-view__split {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.review-view__sider {
  width: 280px;
  flex-shrink: 0;
  position: sticky;
  top: 24px;
  max-height: calc(100vh - 120px);
}

.review-view__main {
  flex: 1;
  min-width: 0;
}

/* 窄屏：左右分栏改纵向堆叠，侧栏占满宽度 */
@media (max-width: 1200px) {
  .review-view__split {
    flex-direction: column;
  }
  .review-view__sider {
    width: 100%;
    position: static;
    max-height: none;
  }
}

.review-view__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}
</style>
