<template>
  <PageContainer
    title="招标解析"
    subtitle="上传招标文件 → 智能解析评分点 → 人工确认后生成大纲"
  >
    <LoadingSkeleton
      v-if="loading"
      :rows="5"
    />
    <ErrorState
      v-else-if="loadError"
      :description="loadError"
    >
      <template #action>
        <a-button
          type="primary"
          @click="fetchData"
        >
          重试
        </a-button>
      </template>
    </ErrorState>
    <ParseConfirmView
      v-else-if="hasData && !hasPendingDoc"
      :embedded="true"
    />
    <a-card
      v-else
      class="parse-card"
    >
      <!-- 公司资料引导：二期起公司素材统一在全局资料库管理 -->
      <a-alert
        type="info"
        show-icon
        class="mb-4"
        message="公司资料（产品手册/历史方案/资质证书）已迁移至「全局资料库」统一管理"
      >
        <template #action>
          <a-button
            size="small"
            type="link"
            @click="router.push({ name: 'Materials' })"
          >
            前往全局资料库
          </a-button>
        </template>
      </a-alert>

      <!-- 招标文件上传（tender_file：上传后自动入队解析） -->
      <a-upload-dragger
        v-model:file-list="uploadList"
        :multiple="false"
        accept=".pdf,.doc,.docx"
        :before-upload="beforeUpload"
        :custom-request="handleUpload"
        :show-upload-list="true"
        class="mb-4"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p class="ant-upload-text">
          点击或拖拽招标文件到此区域上传
        </p>
        <p class="ant-upload-hint">
          支持 PDF / Word 格式，单文件不超过 50MB，上传后自动解析评分点
        </p>
      </a-upload-dragger>

      <!-- 已上传招标文件列表（解析状态跟踪） -->
      <a-table
        v-if="tenderDocs.length > 0"
        :columns="tenderColumns"
        :data-source="tenderDocs"
        :pagination="false"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">
              {{ statusText(record.status) }}
            </a-tag>
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
        </template>
      </a-table>
      <div
        v-if="tenderDocs.length > 0"
        class="parse-card__refresh"
      >
        <a-space>
          <a-tag
            v-if="hasPendingDoc"
            color="processing"
          >
            解析中，页面将自动刷新
          </a-tag>
          <a-button
            :loading="loading"
            @click="fetchData"
          >
            刷新
          </a-button>
        </a-space>
      </div>
    </a-card>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { InboxOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import {
  fetchScorePoints,
  fetchTechRequirements,
  fetchProjectDocuments,
  uploadTenderDocument,
} from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ParseConfirmView from '@/views/parse/ParseConfirmView.vue'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

interface TenderDocument {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
}

const loading = ref(false)
const loadError = ref('')
const scorePointCount = ref(0)
const techRequirementCount = ref(0)
const uploadList = ref<UploadFile[]>([])
const tenderDocs = ref<TenderDocument[]>([])

const tenderColumns = [
  { title: '文件名', dataIndex: 'title', key: 'title' },
  { title: '状态', key: 'status', width: 120 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
]

/** 已有解析数据（评分点或技术需求任一非空）→ 内嵌确认页；
 * 存在解析中文档时优先文件列表态（展示进度并轮询，重新解析场景） */
const hasData = computed(() => scorePointCount.value > 0 || techRequirementCount.value > 0)

/** 存在未完成的解析任务（uploaded/parsing）→ 自动轮询直到出结果 */
const hasPendingDoc = computed(() =>
  tenderDocs.value.some((d) => d.status === 'uploaded' || d.status === 'parsing'),
)

let pollTimer: number | null = null

const stopPolling = () => {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

const schedulePolling = () => {
  if (pollTimer !== null || !hasPendingDoc.value) return
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    fetchData()
  }, 5000)
}

const fetchData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [spRes, trRes] = await Promise.all([
      fetchScorePoints(projectId),
      fetchTechRequirements(projectId),
    ])
    scorePointCount.value = (spRes.data?.data as unknown[])?.length || 0
    techRequirementCount.value = (trRes.data?.data as unknown[])?.length || 0
    // 同步拉取招标文件列表：存在解析中文档时展示进度并轮询（重新解析场景）
    await fetchTenderDocs()
  } catch {
    loadError.value = '解析数据加载失败'
  } finally {
    loading.value = false
  }
}

const fetchTenderDocs = async () => {
  try {
    const res = await fetchProjectDocuments(projectId, { doc_type: 'tender_file' })
    tenderDocs.value = res.data?.data?.items || []
    // 解析中→ 5s 后自动复查，直到 parsed/failed 或评分点就绪
    schedulePolling()
  } catch {
    // 列表拉取失败不阻断页面（上传入口仍可用）
  }
}

const statusColor = (status: string): string => {
  const colors: Record<string, string> = {
    uploaded: 'default',
    parsing: 'processing',
    parsed: 'blue',
    indexed: 'success',
    failed: 'error',
  }
  return colors[status] || 'default'
}

const statusText = (status: string): string => {
  const texts: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '已解析',
    indexed: '已完成',
    failed: '失败',
  }
  return texts[status] || status
}

const formatTime = (time?: string): string => {
  if (!time) return '—'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return time
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const beforeUpload: NonNullable<UploadProps['beforeUpload']> = (file) => {
  const isLt50M = file.size / 1024 / 1024 < 50
  if (!isLt50M) {
    message.error('文件大小不能超过 50MB')
  }
  return isLt50M
}

const handleUpload: NonNullable<UploadProps['customRequest']> = async (options) => {
  const file = options.file as File
  const formData = new FormData()
  formData.append('file', file)

  try {
    // 不手动设 Content-Type：axios 自动带 boundary
    const res = await uploadTenderDocument(projectId, formData, (e) => {
      if (e.total) {
        options.onProgress?.({ percent: Math.round((e.loaded / e.total) * 100) })
      }
    })
    options.onSuccess?.(res.data)
    message.success(`${file.name} 上传成功，正在后台解析评分点`)
    fetchTenderDocs()
  } catch (err) {
    options.onError?.(err as Error)
    message.error(`${file.name} 上传失败`)
  }
}

onMounted(fetchData)

onUnmounted(stopPolling)
</script>

<style scoped>
.parse-card {
  background: var(--bg-surface);
}

.mb-4 {
  margin-bottom: 16px;
}

.parse-card__refresh {
  margin-top: 16px;
  text-align: right;
}
</style>
