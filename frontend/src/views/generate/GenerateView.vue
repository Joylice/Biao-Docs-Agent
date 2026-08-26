<template>
  <div class="generate-view">
    <PageContainer
      title="方案大纲生成"
      :subtitle="outlineConfirmed ? '大纲已确认，可在分工页编制章节内容' : undefined"
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
        <template v-else-if="outline.length > 0">
          <!-- 大纲待确认编辑区 -->
          <OutlineEditPanel
            v-if="awaitingOutlineConfirm"
            ref="outlineEditRef"
            :outline="outline"
            :project-id="projectId"
            :generating="false"
            :can-edit-outline-now="canEditOutlineNow"
            @confirm="handleConfirmOutline"
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
              <!-- 大纲确认后引导跳转分工页 -->
              <a-alert
                v-if="outlineConfirmed"
                type="success"
                show-icon
                banner
                class="generate-view__guide"
                message="大纲已确认，请前往分工页进行章节编制"
                description="章节内容编制在「方案生成与分工」页面完成，本页仅做预览"
              >
                <template #action>
                  <a-button
                    type="primary"
                    size="small"
                    @click="goToDivision"
                  >
                    前往分工编制
                  </a-button>
                </template>
              </a-alert>
              <GenerateTabsPanel
                :selected-chapter="selectedChapter"
                :project-id="projectId"
                :phase="phase"
                @go-division="goToDivision"
              />
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="generate-view__actions">
            <a-popconfirm
              v-if="awaitingOutlineConfirm && canEditOutlineNow"
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
          </div>
        </template>

        <!-- 空状态 -->
        <EmptyState
          v-else
          description="尚未开始生成，点击下方按钮开始生成技术方案大纲"
        >
          <template #action>
            <a-button
              v-if="canEditOutlineNow"
              type="primary"
              :loading="regeneratingOutline"
              @click="handleStartWorkflow"
            >
              开始生成大纲
            </a-button>
          </template>
        </EmptyState>
      </template>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  fetchDisqualificationClauses,
  fetchWorkflowStatus,
  fetchProject,
  startWorkflow,
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

const { isProjectOwner, canEditOutline } = usePermission()
const projectOwnerId = ref('')
const canEditOutlineNow = computed(() => canEditOutline(isProjectOwner(projectOwnerId.value)))

// 状态
const regeneratingOutline = ref(false)
const confirming = ref(false)
const outline = ref<OutlineItem[]>([])
const selectedChapter = ref('')
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
    !outlinePolling.value &&
    (phase.value === 'init' || interruptType.value === 'confirm_score_points'),
)

const awaitingOutlineConfirm = computed(
  () => interruptType.value === 'confirm_outline',
)

/** 大纲已确认（phase 已过 outline 阶段，或 interrupt 已清除） */
const outlineConfirmed = computed(
  () =>
    outline.value.length > 0 &&
    !awaitingOutlineConfirm.value &&
    interruptType.value !== 'confirm_score_points',
)

/* ---------------- 废标条款 ---------------- */
const loadDisqualificationClauses = async () => {
  try {
    const res = await fetchDisqualificationClauses(projectId)
    disqualificationClauses.value = res.data?.data?.items || []
  } catch { disqualificationClauses.value = [] }
}

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

/** 启动工作流（空状态页"开始生成大纲"按钮） */
const handleStartWorkflow = async () => {
  regeneratingOutline.value = true
  try {
    await startWorkflow(projectId)
    message.success('工作流已启动，正在生成大纲...')
    startOutlinePolling()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '启动大纲生成失败')
  } finally { regeneratingOutline.value = false }
}

/** 确认大纲 → 不再在本页启动章节生成，仅确认后引导去分工页 */
const handleConfirmOutline = async () => {
  const editedTree = outlineEditRef.value?.getTree() ?? []
  if (editedTree.length === 0) { message.warning('大纲不能为空'); return }
  for (const c of editedTree) {
    if (!c.title.trim()) { message.warning('章节存在空标题'); return }
  }
  confirming.value = true
  try {
    const body: Partial<ConfirmOutlineRequest> = {
      outline: treeToOutline(editedTree),
      mounted_doc_ids: null,
      mounted_kb_ids: null,
      // 2026-08-25：由分工驱动编制，确认后不自动批量生成章节
      start_generation: false,
    }
    await confirmOutline(projectId, body)
    outlineEditRef.value?.clearDraft()
    message.success('大纲已确认，请前往分工页进行章节编制')
    await loadInitial()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '确认大纲失败')
  } finally { confirming.value = false }
}

const goToDivision = () => router.push({ name: 'Division', params: { projectId } })

const loadInitial = async () => {
  loadError.value = ''
  try {
    const res = await fetchWorkflowStatus(projectId)
    const data = res.data?.data
    phase.value = data?.phase || 'init'
    interruptType.value = data?.interrupt?.type || ''
    if (data?.outline?.length) {
      outline.value = data.outline
      stopOutlinePolling()
      if (!selectedChapter.value && outline.value.length > 0) {
        selectedChapter.value = outline.value[0].chapter_no
      }
    } else if (
      phase.value !== 'init' &&
      interruptType.value !== 'confirm_score_points'
    ) {
      startOutlinePolling()
    }
  } catch { loadError.value = '方案状态加载失败' }
}

onMounted(() => {
  loadInitial()
  loadDisqualificationClauses()
  fetchProjectOwner()
  fetchAssignments()
})

onUnmounted(() => {
  stopOutlinePolling()
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

.generate-view__guide {
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
