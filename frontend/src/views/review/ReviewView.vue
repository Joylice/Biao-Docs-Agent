<template>
  <div class="review-view">
    <PageContainer title="审阅与导出" subtitle="审阅生成内容，提交修改意见或确认导出">
      <a-alert
        v-if="rewriting"
        type="info"
        show-icon
        class="mb-4"
        message="章节重写中，请稍候，完成后将自动刷新审阅内容"
      />

      <LoadingSkeleton v-if="loading" :rows="6" />
      <ErrorState v-else-if="loadError" :description="loadError">
        <template #action>
          <a-button type="primary" @click="fetchStatus">重试</a-button>
        </template>
      </ErrorState>
      <EmptyState v-else-if="chapterKeys.length === 0" description="暂无章节内容，请先在「方案大纲生成」页生成技术方案" />

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
              :active-chapter="activeChapter"
              :active-chapter-title="activeChapterTitle"
              :submitter="submitterOf(activeChapter)"
              v-model:mode="mode"
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
              v-model:new-annotation="newAnnotation"
              :adding-annotation="addingAnnotation"
              :project-id="projectId"
              :is-owner="isOwner"
              :current-user-id="currentUserId"
              @approve="handleApprove"
              @open-feedback="openFeedbackDrawer"
              @save="handleSaveEditDraft"
              @reset="resetEditDraft"
              @update:edit-content="(val) => (editDrafts[activeChapter] = val)"
              @add-annotation="handleAddAnnotation(activeChapter)"
              @edit-annotation="startEditAnnotation"
              @delete-annotation="(id) => handleDeleteAnnotation(activeChapter, id)"
              @load-annotations="loadAnnotations"
            />
          </div>
        </div>

        <!-- 底部操作区 -->
        <div class="review-view__actions">
          <a-button @click="goToGenerate">返回修改</a-button>
          <a-button type="primary" :loading="exporting" size="large" @click="handleExport">
            导出 Word 文档
          </a-button>
          <a-button :loading="approving" :disabled="polling" size="large" @click="handleApprove">
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
            <a-button @click="handleDownload">下载文档</a-button>
          </template>
        </a-result>

        <!-- 版本库 -->
        <ReviewVersionPanel
          :versions="versions"
          :is-owner="isOwner"
          :snapshotting="snapshotting"
          :rolling-back-id="rollingBackId"
          @open-snapshot="openSnapshotModal"
          @download="handleDownloadVersion"
          @archive="openArchiveModal"
          @rollback="confirmRollback"
        />
      </template>
    </PageContainer>

    <!-- 手动快照弹窗 -->
    <a-modal
      v-model:open="snapshotModalOpen"
      title="手动创建版本快照"
      ok-text="创建快照"
      cancel-text="取消"
      :confirm-loading="snapshotting"
      @ok="handleCreateSnapshot"
    >
      <a-form layout="vertical">
        <a-form-item label="备注（可选）">
          <a-textarea v-model:value="snapshotNote" :rows="3" placeholder="例如：评审定稿版" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 归档弹窗 -->
    <a-modal
      v-model:open="archiveModalOpen"
      title="归档到公司知识库"
      ok-text="归档"
      cancel-text="取消"
      :confirm-loading="archiving"
      :ok-button-props="{ disabled: !archiveKbId }"
      @ok="handleArchive"
    >
      <a-form layout="vertical">
        <a-form-item label="目标知识库">
          <a-select v-model:value="archiveKbId" :options="companyBases" placeholder="选择公司级知识库" />
        </a-form-item>
        <div class="hint">归档后版本文档将入公司库分块向量化，供全公司方案生成检索</div>
      </a-form>
    </a-modal>

    <!-- 反馈重写抽屉 -->
    <a-drawer v-model:open="feedbackDrawerOpen" title="反馈重写" placement="right" :width="440">
      <a-form layout="vertical">
        <a-form-item label="目标章节">
          <a-tag color="blue">章节 {{ activeChapter }}</a-tag>
        </a-form-item>
        <a-form-item label="修改意见">
          <a-textarea
            v-model:value="feedbackComment"
            :rows="8"
            placeholder="描述需要修改的内容，例如：补充行业成功案例"
          />
          <div class="hint">意见将回派给章节负责人；无分工的章节由 AI 重写</div>
        </a-form-item>
      </a-form>
      <div class="drawer-footer">
        <a-button @click="feedbackDrawerOpen = false">取消</a-button>
        <a-button type="primary" :loading="submittingFeedback" @click="handleSubmitChapterFeedback">
          提交重写
        </a-button>
      </div>
    </a-drawer>

    <!-- 批注编辑弹窗 -->
    <a-modal
      v-model:open="annotationEditModalOpen"
      title="编辑批注"
      ok-text="保存"
      cancel-text="取消"
      :confirm-loading="updatingAnnotation"
      @ok="handleUpdateAnnotationConfirm"
    >
      <a-textarea v-model:value="editingAnnotationContent" :rows="4" :maxlength="2000" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { ExclamationCircleOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ReviewChapterList from './components/ReviewChapterList.vue'
import ReviewContentPanel from './components/ReviewContentPanel.vue'
import ReviewVersionPanel from './components/ReviewVersionPanel.vue'

interface WorkflowInterrupt { type: string; message?: string }
interface OutlineNode { chapter_no: string; title: string; sections?: string[] }
interface WorkflowStatus {
  phase?: string
  progress?: number
  chapters?: Record<string, string>
  outline?: OutlineNode[]
  review_action?: string
  review_feedback?: Record<string, string>
  export_status?: string
  export_storage_key?: string
  error?: string
  interrupt?: WorkflowInterrupt | null
}
interface VersionItem {
  id: string
  version: number
  snapshot_note: string | null
  created_by: string | null
  created_by_name: string | null
  auto: boolean
  created_at: string | null
}
interface AnnotationItem {
  id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string | null
}
interface RiskItem {
  clause_no: string
  title: string
  severity: string
  risk_category: string
  recommendation: string
}
interface KbBaseOption { value: string; label: string }

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
const submittingFeedback = ref(false)
const exporting = ref(false)
const exportStatus = ref('')
const exportStorageKey = ref('')
const rewriting = ref(false)

// UI 状态
const mode = ref<'edit' | 'preview'>('preview')
const editDrafts = ref<Record<string, string>>({})
const feedbackDrawerOpen = ref(false)
const feedbackComment = ref('')

// 版本库
const isOwner = ref(false)
const versions = ref<VersionItem[]>([])
const snapshotModalOpen = ref(false)
const snapshotNote = ref('')
const snapshotting = ref(false)
const archiveModalOpen = ref(false)
const archiving = ref(false)
const archiveKbId = ref<string | undefined>(undefined)
const archiveTarget = ref<VersionItem | null>(null)
const companyBases = ref<KbBaseOption[]>([])
const rollingBackId = ref('')

// 批注
const annotationMap = ref<Record<string, AnnotationItem[]>>({})
const annotationLoaded = ref<Record<string, boolean>>({})
const annotationsLoading = ref(false)
const newAnnotation = ref('')
const addingAnnotation = ref(false)
const editingAnnotationId = ref('')
const editingAnnotationContent = ref('')
const updatingAnnotation = ref(false)
const annotationEditModalOpen = ref(false)

// 废标风险
const disqualificationRisks = ref<Record<string, RiskItem[]>>({})

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
    await api.put(`/projects/${projectId}/workflow/sections/${no}`, { content })
    chapters.value[no] = content
    delete editDrafts.value[no]
    message.success(`章节 ${no} 已保存到正式方案`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '章节保存失败')
  } finally { savingSection.value = false }
}

// 批注
const annotationListOf = (chapterNo: string): AnnotationItem[] => annotationMap.value[chapterNo] || []
const annotationCountOf = (chapterNo: string): number => annotationListOf(chapterNo).length

const loadAnnotations = async (chapterNo: string) => {
  if (annotationLoaded.value[chapterNo]) return
  annotationsLoading.value = true
  try {
    const res = await api.get(`/projects/${projectId}/chapters/${chapterNo}/annotations`)
    if (res.data?.code === 0) {
      annotationMap.value[chapterNo] = res.data.data.items || []
      annotationLoaded.value[chapterNo] = true
    }
  } catch { message.error('批注加载失败') }
  finally { annotationsLoading.value = false }
}

const handleAddAnnotation = async (chapterNo: string) => {
  const content = newAnnotation.value.trim()
  if (!chapterNo || !content) return
  addingAnnotation.value = true
  try {
    const res = await api.post(`/projects/${projectId}/chapters/${chapterNo}/annotations`, { content })
    if (res.data?.code === 0) {
      newAnnotation.value = ''
      annotationLoaded.value[chapterNo] = false
      await loadAnnotations(chapterNo)
    }
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    message.error(status === 403 ? '无该章节批注权限' : '批注添加失败')
  } finally { addingAnnotation.value = false }
}

const startEditAnnotation = (item: AnnotationItem) => {
  editingAnnotationId.value = item.id
  editingAnnotationContent.value = item.content
  annotationEditModalOpen.value = true
}

const handleUpdateAnnotationConfirm = async () => {
  const content = editingAnnotationContent.value.trim()
  if (!content || !editingAnnotationId.value) return
  updatingAnnotation.value = true
  try {
    const res = await api.put(
      `/projects/${projectId}/chapters/${activeChapter.value}/annotations/${editingAnnotationId.value}`,
      { content },
    )
    if (res.data?.code === 0) {
      annotationEditModalOpen.value = false
      const items = annotationMap.value[activeChapter.value] || []
      const idx = items.findIndex((it) => it.id === editingAnnotationId.value)
      if (idx >= 0) items[idx] = { ...items[idx], ...res.data.data }
      message.success('批注已更新')
    }
  } catch { message.error('批注更新失败') }
  finally { updatingAnnotation.value = false }
}

const handleDeleteAnnotation = async (chapterNo: string, annotationId: string) => {
  try {
    const res = await api.delete(`/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}`)
    if (res.data?.code === 0) {
      annotationMap.value[chapterNo] = (annotationMap.value[chapterNo] || []).filter(
        (it) => it.id !== annotationId,
      )
      message.success('批注已删除')
    }
  } catch { message.error('批注删除失败') }
}

// 轮询
let pollTimer: number | null = null
const stopPolling = () => { if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null } }

const applyStatus = (data: WorkflowStatus) => {
  chapters.value = data.chapters || {}
  outline.value = data.outline || []
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
  const res = await api.get(`/projects/${projectId}/workflow/status`)
  return res.data?.data as WorkflowStatus | undefined
}

const fetchSubmitters = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/chapter-assignments`)
    const items = (res.data?.data?.items || []) as { chapter_no: string; submitted_by_name?: string }[]
    const map: Record<string, string> = {}
    for (const it of items) { if (it.submitted_by_name) map[it.chapter_no] = it.submitted_by_name }
    submitters.value = map
  } catch { /* 降级 */ }
}

const fetchVersions = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/versions`)
    if (res.data?.code === 0) versions.value = res.data.data.items || []
  } catch { /* 不阻塞 */ }
}

const fetchOwnerFlag = async () => {
  try {
    await fetchCurrentUserRole()
    const res = await api.get(`/projects/${projectId}`)
    if (res.data?.code === 0) isOwner.value = res.data.data.owner_id === currentUserId.value
  } catch { isOwner.value = false }
}

const fetchDisqualificationRisks = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/disqualification-risks`)
    disqualificationRisks.value = res.data?.data?.risks || {}
  } catch { disqualificationRisks.value = {} }
}

// 版本操作
const openSnapshotModal = () => { snapshotNote.value = ''; snapshotModalOpen.value = true }

const handleCreateSnapshot = async () => {
  snapshotting.value = true
  try {
    const res = await api.post(`/projects/${projectId}/versions`, { snapshot_note: snapshotNote.value.trim() || null })
    if (res.data?.code === 0) {
      message.success(`版本 v${res.data.data.version} 快照已创建`)
      snapshotModalOpen.value = false
      await fetchVersions()
    }
  } catch { message.error('快照创建失败') }
  finally { snapshotting.value = false }
}

const handleDownloadVersion = async (item: VersionItem, type: 'docx' | 'source') => {
  try {
    const res = await api.get(`/projects/${projectId}/versions/${item.id}/download`, { params: { type } })
    if (res.data?.code === 0 && res.data.data.url) window.open(res.data.data.url, '_blank')
  } catch { message.error('下载链接生成失败') }
}

const openArchiveModal = async (item: VersionItem) => {
  archiveTarget.value = item
  archiveKbId.value = undefined
  archiveModalOpen.value = true
  if (companyBases.value.length > 0) return
  try {
    const res = await api.get('/kb-bases')
    if (res.data?.code === 0) {
      companyBases.value = (res.data.data.items || [])
        .filter((b: { scope: string }) => b.scope === 'company')
        .map((b: { id: string; name: string }) => ({ value: b.id, label: b.name }))
    }
  } catch { message.error('知识库列表加载失败') }
}

const handleArchive = async () => {
  if (!archiveTarget.value || !archiveKbId.value) return
  archiving.value = true
  try {
    const res = await api.post(`/projects/${projectId}/versions/${archiveTarget.value.id}/archive`, { kb_id: archiveKbId.value })
    if (res.data?.code === 0) { message.success(`已归档：${res.data.data.title}`); archiveModalOpen.value = false }
  } catch { message.error('归档失败') }
  finally { archiving.value = false }
}

const confirmRollback = (item: VersionItem) => {
  Modal.confirm({
    title: '回滚版本',
    content: `将用版本 v${item.version} 的快照覆盖当前全部章节内容。确认回滚？`,
    okText: '确认回滚',
    cancelText: '取消',
    okButtonProps: { danger: true },
    icon: () => h(ExclamationCircleOutlined),
    onOk: () => handleRollback(item),
  })
}

const handleRollback = async (item: VersionItem) => {
  rollingBackId.value = item.id
  try {
    const res = await api.post(`/projects/${projectId}/versions/${item.id}/rollback`)
    if (res.data?.code !== 0) { message.error(res.data?.message || '版本回滚失败'); return }
    const restored = res.data.data?.chapters_restored ?? 0
    await fetchVersions()
    const data = await fetchStatus()
    if (data) { applyStatus(data); editDrafts.value = {} }
    message.success(`回滚成功，已恢复 ${restored} 个章节内容`)
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    message.error(status === 403 ? '仅项目负责人可回滚' : '版本回滚失败')
  } finally { rollingBackId.value = '' }
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
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, { action: 'approved' })
    if (res.data?.code !== 0) { message.error(res.data?.message || '审阅确认失败'); return }
    message.success('审阅通过，正在生成导出文档...')
    pollUntil((data) => data.export_status === 'done', () => message.success('导出完成，可下载文档'))
  } catch { message.error('审阅确认失败') }
  finally { approving.value = false }
}

const openFeedbackDrawer = () => { feedbackComment.value = ''; feedbackDrawerOpen.value = true }

const handleSubmitChapterFeedback = async () => {
  const comment = feedbackComment.value.trim()
  if (!comment) { message.warning('请填写修改意见'); return }
  if (!activeChapter.value) { message.warning('请先选择章节'); return }
  submittingFeedback.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'feedback',
      feedback: { [activeChapter.value]: comment },
    })
    if (res.data?.code !== 0) { message.error(res.data?.message || '提交修改意见失败'); return }
    if (res.data?.data?.next_phase === 'redispatch') {
      message.success('修改意见已回派给章节负责人，重编提交后复审')
      feedbackDrawerOpen.value = false
      return
    }
    message.success('修改意见已提交，已触发章节重写')
    feedbackDrawerOpen.value = false
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
  } catch { message.error('提交修改意见失败') }
  finally { submittingFeedback.value = false }
}

const handleExport = async () => {
  exporting.value = true
  try {
    const res = await api.get(`/projects/${projectId}/workflow/export`)
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
    await fetchOwnerFlag()
    await fetchVersions()
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

.review-view__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
