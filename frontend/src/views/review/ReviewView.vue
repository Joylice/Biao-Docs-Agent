<template>
  <div class="review-view">
    <a-page-header title="审阅与导出" sub-title="审阅生成内容，确认导出" />

    <a-alert
      v-if="rewriting"
      type="info"
      show-icon
      class="mb-4"
      message="章节重写中，请稍候，完成后将自动刷新审阅内容"
    />

    <a-spin :spinning="loading">
      <!-- 审阅意见（按章节填写，提交后触发重写） -->
      <a-card title="审阅意见" class="mb-4" v-if="chapterKeys.length > 0">
        <a-list :data-source="chapterKeys" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <div class="feedback-item">
                <div class="feedback-item-title">
                  <a-tag color="blue">章节 {{ item }}</a-tag>
                  <span v-if="reviewFeedback[item]" class="feedback-last">
                    上次意见：{{ reviewFeedback[item] }}
                  </span>
                </div>
                <a-textarea
                  v-model:value="feedbackDrafts[item]"
                  :rows="2"
                  placeholder="填写该章节修改意见（无意见可留空）"
                />
              </div>
            </a-list-item>
          </template>
        </a-list>
      </a-card>

      <!-- 章节内容浏览 -->
      <a-card title="章节内容" class="mb-4">
        <a-tabs v-model:activeKey="activeChapter">
          <a-tab-pane v-for="(content, chapterNo) in chapters" :key="chapterNo" :tab="`章节 ${chapterNo}`">
            <div class="chapter-content" v-html="renderContent(content)"></div>
          </a-tab-pane>
        </a-tabs>
      </a-card>
    </a-spin>

    <!-- 导出操作 -->
    <div class="actions">
      <a-button @click="goToGenerate">返回修改</a-button>
      <a-button type="primary" @click="handleExport" :loading="exporting" size="large">
        导出 Word 文档
      </a-button>
      <a-button
        type="primary"
        ghost
        @click="handleApprove"
        :loading="approving"
        :disabled="polling"
        size="large"
      >
        审阅通过
      </a-button>
      <a-button
        type="primary"
        @click="handleSubmitFeedback"
        :loading="submittingFeedback"
        :disabled="polling"
        size="large"
      >
        提交修改意见
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
        <a-button type="primary" @click="handleDownload">下载文档</a-button>
      </template>
    </a-result>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'

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
const chapters = ref<Record<string, string>>({})
const activeChapter = ref('')
const reviewFeedback = ref<Record<string, string>>({})
const feedbackDrafts = ref<Record<string, string>>({})
const approving = ref(false)
const submittingFeedback = ref(false)
const exporting = ref(false)
const exportStatus = ref('')
const exportStorageKey = ref('')
const rewriting = ref(false)

const chapterKeys = computed(() => Object.keys(chapters.value))
const polling = computed(() => pollTimer !== null)

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
  // 初始化意见草稿（保留已输入内容）
  for (const chapterNo of Object.keys(chapters.value)) {
    if (feedbackDrafts.value[chapterNo] === undefined) {
      feedbackDrafts.value[chapterNo] = ''
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

const handleSubmitFeedback = async () => {
  const feedback: Record<string, string> = {}
  for (const chapterNo of Object.keys(feedbackDrafts.value)) {
    const comment = (feedbackDrafts.value[chapterNo] || '').trim()
    if (comment) feedback[chapterNo] = comment
  }
  if (Object.keys(feedback).length === 0) {
    message.warning('请先填写至少一条修改意见')
    return
  }
  submittingFeedback.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'feedback',
      feedback,
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '提交修改意见失败')
      return
    }
    message.success('修改意见已提交，已触发章节重写')
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
        feedbackDrafts.value = {}
        for (const chapterNo of Object.keys(chapters.value)) {
          feedbackDrafts.value[chapterNo] = ''
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

const renderContent = (content: string) => {
  return content
    .replace(/### (.*)/g, '<h3>$1</h3>')
    .replace(/## (.*)/g, '<h2>$1</h2>')
    .replace(/\n\n/g, '<br/><br/>')
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
  try {
    const data = await fetchStatus()
    if (data) applyStatus(data)
  } catch {
    message.error('加载审阅状态失败')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.review-view { max-width: 1000px; }
.mb-4 { margin-bottom: 16px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
.chapter-content { max-height: 500px; overflow-y: auto; line-height: 1.8; }
.feedback-item { width: 100%; }
.feedback-item-title { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.feedback-last { color: #999; font-size: 12px; }
</style>
