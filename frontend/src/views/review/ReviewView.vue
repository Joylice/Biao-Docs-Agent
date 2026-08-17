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
        description="暂无章节内容，请先在「方案生成」页生成技术方案"
      />
      <template v-else>
        <!-- 左章节树 + 右内容 分栏 -->
        <a-layout
          class="review-layout"
          has-sider
        >
          <a-layout-sider
            v-model:collapsed="siderCollapsed"
            :width="232"
            :collapsed-width="0"
            breakpoint="lg"
            theme="light"
            class="review-sider"
          >
            <div class="review-sider__title">
              章节列表
              <a-tooltip :title="siderCollapsed ? '展开章节' : '收起章节'">
                <a-button
                  size="small"
                  type="text"
                  @click="siderCollapsed = !siderCollapsed"
                >
                  <template #icon>
                    <MenuFoldOutlined v-if="!siderCollapsed" />
                    <MenuUnfoldOutlined v-else />
                  </template>
                </a-button>
              </a-tooltip>
            </div>
            <a-list
              v-if="!siderCollapsed"
              :data-source="chapterKeys"
              size="small"
              class="chapter-tree"
            >
              <template #renderItem="{ item }">
                <a-list-item
                  class="chapter-node"
                  :class="{ 'chapter-node--active': activeChapter === item }"
                  @click="selectChapter(item)"
                >
                  <div class="chapter-node__row">
                    <div class="chapter-node__no">
                      章节 {{ item }}
                    </div>
                    <a-tag
                      :color="chapterStateColor(item)"
                      class="chapter-node__tag"
                    >
                      {{ chapterStateText(item) }}
                    </a-tag>
                  </div>
                </a-list-item>
              </template>
            </a-list>
          </a-layout-sider>

          <a-layout-content class="review-content">
            <!-- 顶部操作条 -->
            <div class="review-toolbar">
              <a-segmented
                v-model:value="mode"
                :options="modeOptions"
              />
              <a-button
                type="primary"
                size="small"
                ghost
                :loading="approving"
                :disabled="polling"
                @click="handleApprove"
              >
                通过
              </a-button>
              <a-button
                size="small"
                :disabled="polling"
                @click="openFeedbackDrawer"
              >
                反馈重写
              </a-button>
              <a-button
                v-if="mode === 'edit'"
                size="small"
                @click="resetEditDraft"
              >
                重置
              </a-button>
            </div>

            <!-- 章节内容：编辑 / 预览 -->
            <a-card
              :title="`章节 ${activeChapter}`"
              class="chapter-card"
            >
              <a-textarea
                v-if="mode === 'edit'"
                v-model:value="editDrafts[activeChapter]"
                :rows="18"
                class="chapter-editor"
              />
              <MarkdownRenderer
                v-else
                :source="displayContent"
              />
            </a-card>
            <div class="feedback-hint">
              <InfoCircleOutlined /> 编辑内容仅保存在本地，提交「反馈重写」后将触发 AI 重写章节
            </div>
          </a-layout-content>
        </a-layout>

        <!-- 底部操作区 -->
        <div class="actions">
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
            type="primary"
            ghost
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
            <a-button
              type="primary"
              @click="handleDownload"
            >
              下载文档
            </a-button>
          </template>
        </a-result>
      </template>
    </PageContainer>

    <!-- 反馈重写面板 -->
    <a-drawer
      v-model:open="feedbackDrawerOpen"
      title="反馈重写"
      placement="right"
      :width="440"
    >
      <a-form layout="vertical">
        <a-form-item label="目标章节">
          <a-tag color="blue">
            章节 {{ activeChapter }}
          </a-tag>
        </a-form-item>
        <a-form-item label="修改意见">
          <a-textarea
            v-model:value="feedbackComment"
            :rows="8"
            placeholder="描述需要修改的内容，例如：补充行业成功案例、调整表述为第一人称等"
          />
        </a-form-item>
      </a-form>
      <div class="drawer-footer">
        <a-button @click="feedbackDrawerOpen = false">
          取消
        </a-button>
        <a-button
          type="primary"
          :loading="submittingFeedback"
          @click="handleSubmitChapterFeedback"
        >
          提交重写
        </a-button>
      </div>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { InfoCircleOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

interface WorkflowInterrupt {
  type: 'confirm_score_points' | 'confirm_outline' | 'review_request'
  message?: string
}

interface WorkflowStatus {
  phase?: string
  progress?: number
  chapters?: Record<string, string>
  review_action?: string
  review_feedback?: Record<string, string>
  export_status?: string
  export_storage_key?: string
  error?: string
  interrupt?: WorkflowInterrupt | null
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
const chapters = ref<Record<string, string>>({})
const activeChapter = ref('')
const reviewFeedback = ref<Record<string, string>>({})
const approving = ref(false)
const submittingFeedback = ref(false)
const exporting = ref(false)
const exportStatus = ref('')
const exportStorageKey = ref('')
const rewriting = ref(false)

// 展示层状态：侧栏折叠 / 编辑-预览模式 / 本地编辑草稿 / 反馈面板
const siderCollapsed = ref(false)
const mode = ref<'edit' | 'preview'>('preview')
const modeOptions = [
  { label: '预览', value: 'preview' },
  { label: '编辑', value: 'edit' },
]
const editDrafts = ref<Record<string, string>>({})
const feedbackDrawerOpen = ref(false)
const feedbackComment = ref('')

const chapterKeys = computed(() => Object.keys(chapters.value))
const polling = computed(() => pollTimer !== null)

/** 展示内容：本地编辑草稿优先，无草稿时用服务端章节原文 */
const displayContent = computed(
  () => editDrafts.value[activeChapter.value] ?? chapters.value[activeChapter.value] ?? '',
)

/** 章节状态（展示层语义）：曾提交过反馈=待重写，否则=待审 */
const chapterStateText = (chapterNo: string): string => {
  if (reviewFeedback.value[chapterNo]) return '待重写'
  return '待审'
}

const chapterStateColor = (chapterNo: string): string => {
  if (reviewFeedback.value[chapterNo]) return 'orange'
  return 'default'
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

let pollTimer: number | null = null

const stopPolling = () => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const applyStatus = (data: WorkflowStatus) => {
  chapters.value = data.chapters || {}
  reviewFeedback.value = data.review_feedback || {}
  exportStatus.value = data.export_status || ''
  exportStorageKey.value = data.export_storage_key || ''
  if (!activeChapter.value) {
    const keys = Object.keys(chapters.value)
    if (keys.length > 0) activeChapter.value = keys[0]
  }
  // 初始化编辑草稿（保留已输入内容）
  for (const chapterNo of Object.keys(chapters.value)) {
    if (editDrafts.value[chapterNo] === undefined) {
      editDrafts.value[chapterNo] = chapters.value[chapterNo] || ''
    }
  }
}

const fetchStatus = async (): Promise<WorkflowStatus | undefined> => {
  const res = await api.get(`/projects/${projectId}/workflow/status`)
  return res.data?.data as WorkflowStatus | undefined
}

/** 轮询状态直到满足终止条件（最长约 3 分钟）. */
const pollUntil = (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => {
  stopPolling()
  let attempts = 0
  pollTimer = window.setInterval(async () => {
    attempts += 1
    try {
      const data = await fetchStatus()
      if (!data) return
      applyStatus(data)
      if (data.error) {
        stopPolling()
        rewriting.value = false
        message.error(data.error)
        return
      }
      if (until(data)) {
        stopPolling()
        onDone?.(data)
      } else if (attempts >= 90) {
        stopPolling()
        rewriting.value = false
        message.warning('等待超时，请稍后手动刷新状态')
      }
    } catch {
      // 轮询中的瞬时错误不打断，继续重试
    }
  }, 2000)
}

const handleApprove = async () => {
  approving.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'approved',
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '审阅确认失败')
      return
    }
    message.success('审阅通过，正在生成导出文档...')
    pollUntil(
      (data) => data.export_status === 'done',
      () => message.success('导出完成，可下载文档'),
    )
  } catch {
    message.error('审阅确认失败')
  } finally {
    approving.value = false
  }
}

const openFeedbackDrawer = () => {
  feedbackComment.value = ''
  feedbackDrawerOpen.value = true
}

/** 反馈重写：仅提交当前章节的意见（API 结构与原先一致） */
const handleSubmitChapterFeedback = async () => {
  const comment = feedbackComment.value.trim()
  if (!comment) {
    message.warning('请填写修改意见')
    return
  }
  if (!activeChapter.value) {
    message.warning('请先选择章节')
    return
  }
  submittingFeedback.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'feedback',
      feedback: { [activeChapter.value]: comment },
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '提交修改意见失败')
      return
    }
    message.success('修改意见已提交，已触发章节重写')
    feedbackDrawerOpen.value = false
    rewriting.value = true
    // 两段式终止条件：先等 interrupt 消失（后台已消费 resume、重写进行中），
    // 再等 review_request 重现（重写完成），避免被提交瞬间尚未消费的旧 interrupt 误判
    let sawCleared = false
    pollUntil(
      (data) => {
        if (!data.interrupt) sawCleared = true
        return sawCleared && data.interrupt?.type === 'review_request'
      },
      () => {
        rewriting.value = false
        // 重写完成后清除该章意见草稿，保留用户其它草稿
        if (editDrafts.value[activeChapter.value] !== undefined) {
          editDrafts.value[activeChapter.value] = chapters.value[activeChapter.value] || ''
        }
        message.success('章节重写完成，请重新审阅')
      },
    )
  } catch {
    message.error('提交修改意见失败')
  } finally {
    submittingFeedback.value = false
  }
}

const handleExport = async () => {
  exporting.value = true
  try {
    const res = await api.get(`/projects/${projectId}/workflow/export`)
    const data = res.data?.data
    exportStatus.value = data?.export_status || 'pending'
    exportStorageKey.value = data?.export_storage_key || ''
    if (exportStatus.value === 'done') {
      message.success('导出成功')
    }
  } catch {
    message.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const handleDownload = async () => {
  if (!exportStorageKey.value) {
    message.info('文档尚未就绪，请先完成导出')
    return
  }
  message.success(`文档已就绪（存储标识：${exportStorageKey.value}）`)
}

const goToGenerate = () => {
  router.push({ name: 'Generate', params: { projectId } })
}

onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchStatus()
    if (data) applyStatus(data)
  } catch {
    loadError.value = '审阅状态加载失败'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.review-view { max-width: 1200px; }
.mb-4 { margin-bottom: 16px; }

.review-layout {
  background: transparent;
}

.review-sider {
  background: var(--card-bg);
  border-radius: 8px;
  overflow: hidden;
  margin-right: 16px;
}

.review-sider__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
}

.chapter-tree {
  max-height: 560px;
  overflow-y: auto;
}

.chapter-node {
  cursor: pointer;
  padding: 10px 16px !important;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}

.chapter-node:hover {
  background: var(--bg-hover, #f5f7fa);
}

.chapter-node--active {
  background: var(--bg-block, rgba(21, 101, 192, 0.06));
  border-left: 3px solid var(--color-primary);
}

.chapter-node__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.chapter-node__no {
  font-size: 13px;
  font-weight: 500;
}

.chapter-node__tag {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 18px;
}

.review-content {
  background: transparent;
  min-width: 0;
}

.review-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.chapter-card {
  background: var(--card-bg);
  min-height: 360px;
}

.chapter-editor {
  font-family: 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 13px;
  line-height: 1.7;
}

.feedback-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
