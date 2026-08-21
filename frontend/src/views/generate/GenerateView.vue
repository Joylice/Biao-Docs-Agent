<template>
  <div class="generate-view">
    <PageContainer
      title="方案大纲生成"
      :subtitle="`进度: ${Math.round(progress * 100)}%`"
    >
      <!-- 高风险废标条款预警 -->
      <a-alert
        v-if="highRiskClauseCount > 0"
        type="warning"
        show-icon
        banner
        class="generate-view__alert"
        :message="`本项目存在 ${highRiskClauseCount} 条高风险废标条款，请重点关注`"
        description="前往招标解析确认页逐条人工确认"
      />

      <!-- 断线重连提示 -->
      <a-alert
        v-if="wsError"
        type="warning"
        show-icon
        class="generate-view__alert"
        :message="wsError"
      />

      <!-- 加载失败 -->
      <ErrorState
        v-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="loadInitial"
          >
            重试
          </a-button>
        </template>
      </ErrorState>

      <template v-else>
        <!-- 尚未确认评分点 -->
        <EmptyState
          v-if="needConfirmScorePoints"
          description="尚未确认评分点：请先在「招标解析」页确认智能解析的评分点"
        >
          <template #action>
            <a-button
              type="primary"
              @click="router.push({ name: 'Parse', params: { projectId } })"
            >
              前往招标解析
            </a-button>
          </template>
        </EmptyState>

        <!-- 大纲生成中 -->
        <a-card
          v-else-if="outlinePolling"
          class="generate-view__polling"
        >
          <a-alert
            type="info"
            show-icon
            message="方案大纲正在生成中，请稍候..."
          />
          <LoadingSkeleton
            class="mt-4"
            :rows="4"
          />
        </a-card>

        <!-- 主内容区：左右分栏 -->
        <template v-else-if="outline.length > 0 || generating || generated">
          <!-- 大纲待确认编辑区 -->
          <OutlineEditPanel
            v-if="awaitingOutlineConfirm"
            ref="outlineEditRef"
            :outline="outline"
            :project-id="projectId"
            :generating="generating"
            :can-edit-outline-now="canEditOutlineNow"
            @confirm="handleStartGenerate"
          />

          <!-- 左右分栏：大纲树 + 章节预览/评分对标 -->
          <div
            v-else
            class="generate-view__split"
          >
            <div class="generate-view__sider">
              <OutlinePanel
                :outline="outline"
                :selected-chapter="selectedChapter"
                :awaiting-confirm="awaitingOutlineConfirm"
                :assignment-map="assignmentMap"
                @select="selectedChapter = $event"
              />
            </div>
            <div class="generate-view__main">
              <GenerateTabsPanel
                :selected-chapter="selectedChapter"
                :current-chapter="currentChapter"
                :display-chapters="displayChapters"
                :progress="progress"
                :generating="generating"
                :generated="generated"
                :project-id="projectId"
                :phase="phase"
                :can-go-division="canCompileSelectedChapter"
                @close="selectedChapter = ''"
                @go-division="goToDivision"
              />
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="generate-view__actions">
            <a-popconfirm
              v-if="awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
              title="重新生成将覆盖当前大纲，确认继续？"
              ok-text="重新生成"
              cancel-text="取消"
              :confirm-loading="regeneratingOutline"
              @confirm="handleRegenerateOutline"
            >
              <a-button :loading="regeneratingOutline">
                重新生成大纲
              </a-button>
            </a-popconfirm>
            <a-button
              v-if="!awaitingOutlineConfirm && !generating && !generated && canEditOutlineNow"
              type="primary"
              :loading="generating"
              @click="handleStartGenerate"
            >
              开始生成
            </a-button>
            <a-button
              v-if="generated"
              type="primary"
              @click="goToReview"
            >
              进入审阅
            </a-button>
          </div>
        </template>

        <!-- 空状态 -->
        <EmptyState
          v-else
          description="尚未开始生成，点击下方按钮开始生成技术方案"
        >
          <template #action>
            <a-button
              v-if="canEditOutlineNow"
              type="primary"
              :loading="generating"
              @click="handleStartGenerate"
            >
              开始生成
            </a-button>
          </template>
        </EmptyState>
      </template>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  fetchDisqualificationClauses,
  fetchWorkflowStatus,
  fetchProject,
  regenerateOutline,
  confirmOutline,
} from '@/api'
import { usePermission } from '@/composables/usePermission'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import OutlinePanel from './components/OutlinePanel.vue'
import OutlineEditPanel from './components/OutlineEditPanel.vue'
import GenerateTabsPanel from './components/GenerateTabsPanel.vue'
import { useWorkflowPolling } from './composables/useWorkflowPolling'
import { useGenerateWebSocket } from './composables/useGenerateWebSocket'
import { useAssignments } from './composables/useAssignments'
import { treeToOutline } from './utils/outlineTree'
import type {
  OutlineItem,
  DisqualificationClause,
  ConfirmOutlineRequest,
} from '@/types'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const { isProjectOwner, canEditOutline, canEditChapter } = usePermission()
const projectOwnerId = ref('')
const canEditOutlineNow = computed(() => canEditOutline(isProjectOwner(projectOwnerId.value)))

// 状态
const progress = ref(0)
const generating = ref(false)
const generated = ref(false)
const regeneratingOutline = ref(false)
const outline = ref<OutlineItem[]>([])
const chapters = ref<Record<string, string>>({})
const currentChapter = ref('')
const selectedChapter = ref('')
const wsError = ref('')
const loadError = ref('')
const outlineEditRef = ref<InstanceType<typeof OutlineEditPanel> | null>(null)

/* 分工映射（拉取/扁平化下沉 useAssignments） */
const { assignmentMap, fetchAssignments } = useAssignments(projectId)

// 废标条款
const disqualificationClauses = ref<DisqualificationClause[]>([])
const highRiskClauseCount = computed(
  () => disqualificationClauses.value.filter((c) => c.severity === 'high').length,
)

// 工作流状态
const phase = ref('init')
const interruptType = ref('')

/* ---------------- 大纲轮询（2s / 120 次） ---------------- */
const {
  polling: outlinePolling,
  start: startOutlinePolling,
  stop: stopOutlinePolling,
} = useWorkflowPolling({
  intervalMs: 2000,
  maxCount: 120,
  onTick: async () => {
    await loadInitial()
    return true
  },
  onTimeout: () => {
    loadError.value = '大纲生成超时，请刷新页面后重试'
  },
})

const needConfirmScorePoints = computed(
  () =>
    outline.value.length === 0 &&
    !generating.value &&
    !generated.value &&
    !outlinePolling.value &&
    (phase.value === 'init' || interruptType.value === 'confirm_score_points'),
)

const awaitingOutlineConfirm = computed(
  () => interruptType.value === 'confirm_outline' && !generating.value && !generated.value,
)

const displayChapters = computed(() => chapters.value)


/* ---------------- 方案生成状态轮询（3s / 100 次，WebSocket 兜底） ---------------- */
const {
  start: startGenPolling,
  stop: stopGenPolling,
  resetCount: resetGenPollCount,
} = useWorkflowPolling({
  intervalMs: 3000,
  maxCount: 100,
  onTick: async () => {
    try {
      const res = await fetchWorkflowStatus(projectId)
      const data = res.data?.data
      if (data?.progress >= 0.75 || data?.phase === 'review' || data?.phase === 'done') {
        if (data?.chapters) chapters.value = data.chapters
        markGenerated()
        return false
      }
    } catch { /* 忽略 */ }
    return true
  },
  onTimeout: () => {
    generating.value = false
    wsError.value = '生成状态同步超时'
  },
})

const markGenerated = () => {
  generated.value = true
  generating.value = false
  progress.value = 1
  wsError.value = ''
  stopGenPolling()
}

/* ---------------- 废标条款 ---------------- */
const loadDisqualificationClauses = async () => {
  try {
    const res = await fetchDisqualificationClauses(projectId)
    disqualificationClauses.value = res.data?.data?.items || []
  } catch { disqualificationClauses.value = [] }
}


const canCompileSelectedChapter = computed(() => {
  const no = selectedChapter.value
  if (!no) return false
  const own = assignmentMap.value.get(no)
  const ids: Array<string | null> = [own?.assignee_id ?? null]
  for (const child of own?.children ?? []) ids.push(child.assignee_id)
  return canEditChapter(ids, isProjectOwner(projectOwnerId.value))
})

/* ---------------- WebSocket（连接/消息路由/重连下沉 useGenerateWebSocket） ---------------- */
const {
  connect: connectWebSocket,
  resetReconnectAttempts: resetWsReconnect,
  dispose: disposeWebSocket,
} = useGenerateWebSocket(projectId, {
  progress,
  chapters,
  currentChapter,
  generating,
  selectedChapter,
  wsError,
  onDone: markGenerated,
  onTaskEvent: fetchAssignments,
  onForbidden: () => {
    generating.value = false
    message.error('无权限访问该项目')
  },
})

/* ---------------- 操作 ---------------- */
const fetchProjectOwner = async () => {
  try {
    const { data } = await fetchProject(projectId)
    if (data.code === 0) projectOwnerId.value = data.data?.owner_id || ''
  } catch { /* 静默 */ }
}

const handleRegenerateOutline = async () => {
  regeneratingOutline.value = true
  try {
    await regenerateOutline(projectId)
    message.success('大纲已重新生成')
    await outlineEditRef.value?.clearDraft()
    await loadInitial()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '重新生成大纲失败')
  } finally { regeneratingOutline.value = false }
}

const handleStartGenerate = async () => {
  const editedTree = outlineEditRef.value?.getTree() ?? []
  if (awaitingOutlineConfirm.value) {
    if (editedTree.length === 0) { message.warning('大纲不能为空'); return }
    for (const c of editedTree) {
      if (!c.title.trim()) { message.warning('章节存在空标题'); return }
    }
  }
  generating.value = true
  try {
    const body: Partial<ConfirmOutlineRequest> = { mounted_doc_ids: null, mounted_kb_ids: null }
    if (awaitingOutlineConfirm.value) body.outline = treeToOutline(editedTree)
    await confirmOutline(projectId, body)
    outlineEditRef.value?.clearDraft()
    resetWsReconnect()
    resetGenPollCount()
    startGenPolling()
    connectWebSocket()
    message.info('开始生成方案...')
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '启动生成失败')
    generating.value = false
  }
}

const goToDivision = () => router.push({ name: 'Division', params: { projectId } })
const goToReview = () => router.push({ name: 'Review', params: { projectId } })

const loadInitial = async () => {
  loadError.value = ''
  try {
    const res = await fetchWorkflowStatus(projectId)
    const data = res.data?.data
    phase.value = data?.phase || 'init'
    interruptType.value = data?.interrupt?.type || ''
    if (data?.outline?.length) {
      outline.value = data.outline
      chapters.value = data.chapters || {}
      progress.value = data.progress || 0
      generated.value = progress.value >= 0.75
      stopOutlinePolling()
      if (!selectedChapter.value && outline.value.length > 0) {
        selectedChapter.value = outline.value[0].chapter_no
      }
    } else if (
      !generated.value &&
      phase.value !== 'init' &&
      interruptType.value !== 'confirm_score_points'
    ) {
      startOutlinePolling()
    }
  } catch { loadError.value = '方案状态加载失败' }
}

watch(currentChapter, (no) => {
  if (no && generating.value && !selectedChapter.value) selectedChapter.value = no
})

onMounted(() => {
  loadInitial()
  loadDisqualificationClauses()
  fetchProjectOwner()
  fetchAssignments()
})

onUnmounted(() => {
  disposeWebSocket()
  stopOutlinePolling()
  stopGenPolling()
})
</script>

<style scoped>
.generate-view {
  width: 100%;
}

.generate-view__alert {
  margin-bottom: 16px;
}

.generate-view__polling {
  margin-bottom: 16px;
}

.generate-view__split {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.generate-view__sider {
  width: 300px;
  flex-shrink: 0;
  position: sticky;
  top: 24px;
  max-height: calc(100vh - 120px);
}

.generate-view__main {
  flex: 1;
  min-width: 0;
}

/* 窄屏：左右分栏改纵向堆叠，侧栏占满宽度 */
@media (max-width: 1200px) {
  .generate-view__split {
    flex-direction: column;
  }
  .generate-view__sider {
    width: 100%;
    position: static;
    max-height: none;
  }
}

.generate-view__actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

.mt-4 { margin-top: 16px; }
</style>
