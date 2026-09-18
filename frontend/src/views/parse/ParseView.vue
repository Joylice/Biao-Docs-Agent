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
          @click="handleRefresh"
        >
          重试
        </a-button>
      </template>
    </ErrorState>

    <!-- 已有解析数据：招标文件区块（默认收起为一行，可展开）注入「评分点」tab 之上.
         上传是第一步动作，原先排在页面最底部、与评分点确认区隔了整屏，故上移。 -->
    <ParseConfirmView
      v-else-if="hasData"
      :embedded="true"
    >
      <template #before-tabs>
        <a-alert
          v-if="hasPendingDoc"
          type="info"
          show-icon
          class="parse-pending-alert"
          :message="`还有 ${pendingCount} 个文件解析中，当前展示已解析结果，解析完成后自动更新`"
        />
        <TenderFileCard
          v-model:file-list="uploadList"
          v-model:expanded="tenderExpanded"
          class="mb-4"
          :docs="tenderDocs"
          :loading="loading"
          :reparse-id="reparseId"
          :collapsible="true"
          :before-upload="beforeUpload"
          @upload="handleUpload"
          @reparse="handleReparse"
          @delete="handleDelete"
          @refresh="handleRefresh"
          @goto-materials="gotoMaterials"
        />
      </template>
    </ParseConfirmView>

    <!-- 尚未解析出评分点：整页即上传入口（形态不变，不做收起） -->
    <TenderFileCard
      v-else
      v-model:file-list="uploadList"
      :docs="tenderDocs"
      :loading="loading"
      :reparse-id="reparseId"
      :before-upload="beforeUpload"
      @upload="handleUpload"
      @reparse="handleReparse"
      @delete="handleDelete"
      @refresh="handleRefresh"
      @goto-materials="gotoMaterials"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import {
  fetchScorePoints,
  fetchProjectDocuments,
  uploadTenderDocument,
  reparseTenderDocument,
  deleteProjectDocument,
} from '@/api'
import { Modal } from 'ant-design-vue'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ParseConfirmView from '@/views/parse/ParseConfirmView.vue'
import TenderFileCard from '@/views/parse/components/TenderFileCard.vue'
import { pendingTenderDocs, type TenderDoc } from '@/utils/tenderDoc'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
const scorePointCount = ref(0)
const uploadList = ref<UploadFile[]>([])
const tenderDocs = ref<TenderDoc[]>([])
/** 招标文件区块展开态（有数据时默认收起为一行摘要） */
const tenderExpanded = ref(false)
const reparseId = ref<string | null>(null)

/** 已有解析数据（评分点非空）→ 内嵌确认页（统计卡 + 评分点 tab） */
const hasData = computed(() => scorePointCount.value > 0)

/** 进行中的解析任务（uploaded/parsing 且未超时）→ 自动轮询直到出结果 */
const pendingDocs = computed(() => pendingTenderDocs(tenderDocs.value))
const hasPendingDoc = computed(() => pendingDocs.value.length > 0)
const pendingCount = computed(() => pendingDocs.value.length)

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
    // 轮询静默刷新：不闪全页骨架屏（已在展示确认页/文件列表时避免频闪）
    fetchData(true)
  }, 5000)
}

/** 手动刷新（重试按钮/刷新按钮）：非静默，展示骨架屏 */
const handleRefresh = () => fetchData()

/** 前往全局资料库（公司素材统一入口） */
const gotoMaterials = () => router.push({ name: 'Materials' })

const fetchData = async (silent = false) => {
  // 轮询（silent）不触发全页 LoadingSkeleton，避免解析中每 5s 频闪；
  // 仅首次/手动刷新展示骨架屏。
  if (!silent) loading.value = true
  loadError.value = ''
  try {
    const spRes = await fetchScorePoints(projectId)
    scorePointCount.value = (spRes.data?.data as unknown[])?.length || 0
    // 同步拉取招标文件列表：存在解析中文档时展示进度并轮询（重新解析场景）
    await fetchTenderDocs()
  } catch {
    loadError.value = '解析数据加载失败'
  } finally {
    if (!silent) loading.value = false
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

/** 重新解析招标文件 */
const handleReparse = async (docId: string) => {
  reparseId.value = docId
  try {
    await reparseTenderDocument(projectId, docId)
    message.success('已重新入队解析，约 1-3 分钟后完成')
    // 重新拉取数据：状态会重置为 uploaded/parsing
    await fetchTenderDocs()
    // 如果当前有数据，重新解析会清除旧评分点，需要刷新计数
    await fetchData()
  } catch {
    message.error('重新解析失败，请稍后重试')
  } finally {
    reparseId.value = null
  }
}

/** 删除招标文件（级联删除关联评分点/技术需求） */
const handleDelete = (docId: string, title: string) => {
  Modal.confirm({
    title: '确认删除',
    content: `删除「${title}」将同时清除其关联的评分点，且不可恢复。确认删除？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await deleteProjectDocument(projectId, docId)
        message.success('删除成功')
        await fetchData()
      } catch {
        message.error('删除失败，请稍后重试')
      }
    },
  })
}

onMounted(fetchData)

onUnmounted(stopPolling)
</script>

<style scoped>
.mb-4 {
  margin-bottom: 16px;
}

.parse-pending-alert {
  margin-bottom: 16px;
}
</style>
