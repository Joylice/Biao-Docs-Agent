<template>
  <a-modal
    :open="visible"
    title="导出 Word 文档"
    :confirm-loading="exporting"
    ok-text="开始导出"
    cancel-text="取消"
    width="520px"
    @ok="handleExport"
    @cancel="handleCancel"
  >
    <!-- 导出选项 -->
    <div v-if="!exporting && exportStatus !== 'done'" class="export-modal__options">
      <div class="export-modal__section">
        <div class="export-modal__section-title">文档内容</div>
        <a-checkbox v-model:checked="options.includeToc">
          包含目录（自动生成）
        </a-checkbox>
        <a-checkbox v-model:checked="options.includeAnnotations">
          包含批注（审阅意见）
        </a-checkbox>
        <a-checkbox v-model:checked="options.includeHeaderFooter">
          包含页眉页脚（页码 + 文档标题）
        </a-checkbox>
      </div>

      <div class="export-modal__section">
        <div class="export-modal__section-title">页面设置</div>
        <div class="export-modal__row">
          <span class="export-modal__label">纸张大小</span>
          <a-radio-group v-model:value="options.paperSize" size="small">
            <a-radio-button value="A4">A4</a-radio-button>
            <a-radio-button value="A3">A3</a-radio-button>
          </a-radio-group>
        </div>
        <div class="export-modal__row">
          <span class="export-modal__label">纸张方向</span>
          <a-radio-group v-model:value="options.orientation" size="small">
            <a-radio-button value="portrait">纵向</a-radio-button>
            <a-radio-button value="landscape">横向</a-radio-button>
          </a-radio-group>
        </div>
      </div>

      <div class="export-modal__section">
        <div class="export-modal__section-title">导出范围</div>
        <a-radio-group v-model:value="options.scope" size="small">
          <a-radio value="all">全部章节</a-radio>
          <a-radio value="current">仅当前章节</a-radio>
        </a-radio-group>
      </div>
    </div>

    <!-- 导出进度 -->
    <div v-if="exporting" class="export-modal__progress">
      <a-progress
        :percent="progressPercent"
        :status="exportStatus === 'failed' ? 'exception' : 'active'"
      />
      <div class="export-modal__progress-text">
        {{ progressText }}
      </div>
      <div v-if="exportStatus === 'failed'" class="export-modal__error">
        <a-alert type="error" :message="errorMessage" show-icon />
      </div>
    </div>

    <!-- 导出完成 -->
    <div v-if="exportStatus === 'done'" class="export-modal__done">
      <a-result
        status="success"
        title="导出成功"
        sub-title="技术方案 Word 文档已生成，可下载编辑"
      >
        <template #extra>
          <a-space>
            <a-button type="primary" @click="handleDownload">
              <template #icon><DownloadOutlined /></template>
              下载文档
            </a-button>
            <a-button @click="handleClose">关闭</a-button>
          </a-space>
        </template>
      </a-result>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DownloadOutlined } from '@ant-design/icons-vue'
import { fetchWorkflowExport } from '@/api'

interface ExportOptions {
  includeToc: boolean
  includeAnnotations: boolean
  includeHeaderFooter: boolean
  paperSize: 'A4' | 'A3'
  orientation: 'portrait' | 'landscape'
  scope: 'all' | 'current'
}

const props = defineProps<{
  visible: boolean
  projectId: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'exported', storageKey: string): void
}>()

const options = ref<ExportOptions>({
  includeToc: true,
  includeAnnotations: false,
  includeHeaderFooter: true,
  paperSize: 'A4',
  orientation: 'portrait',
  scope: 'all',
})

const exporting = ref(false)
const exportStatus = ref<'pending' | 'running' | 'done' | 'failed'>('pending')
const exportStorageKey = ref('')
const errorMessage = ref('')
let pollTimer: number | null = null

const progressPercent = computed(() => {
  if (exportStatus.value === 'done') return 100
  if (exportStatus.value === 'failed') return 0
  if (exportStatus.value === 'running') return 60
  return 20
})

const progressText = computed(() => {
  switch (exportStatus.value) {
    case 'pending': return '正在准备导出...'
    case 'running': return '正在生成 Word 文档...'
    case 'done': return '导出完成'
    case 'failed': return '导出失败'
    default: return ''
  }
})

const stopPolling = () => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const handleExport = async () => {
  exporting.value = true
  exportStatus.value = 'pending'
  errorMessage.value = ''

  try {
    const res = await fetchWorkflowExport(props.projectId)
    const data = res.data?.data
    exportStatus.value = (data?.export_status as 'pending' | 'running' | 'done' | 'failed') || 'pending'
    exportStorageKey.value = data?.export_storage_key || ''

    if (exportStatus.value === 'done') {
      message.success('导出成功')
      return
    }

    // 轮询导出状态
    exportStatus.value = 'running'
    let attempts = 0
    pollTimer = window.setInterval(async () => {
      attempts += 1
      try {
        const pollRes = await fetchWorkflowExport(props.projectId)
        const pollData = pollRes.data?.data
        if (pollData?.export_status === 'done') {
          exportStatus.value = 'done'
          exportStorageKey.value = pollData.export_storage_key || ''
          stopPolling()
          message.success('导出成功')
        } else if (pollData?.export_status === 'failed') {
          exportStatus.value = 'failed'
          errorMessage.value = '导出任务执行失败，请重试'
          stopPolling()
        }
        if (attempts >= 60) {
          exportStatus.value = 'failed'
          errorMessage.value = '导出超时，请稍后重试'
          stopPolling()
        }
      } catch {
        // 继续轮询
      }
    }, 2000)
  } catch (err) {
    exportStatus.value = 'failed'
    const e = err as { response?: { data?: { message?: string } } }
    errorMessage.value = e?.response?.data?.message || '导出失败，请重试'
  }
}

const handleDownload = () => {
  if (!exportStorageKey.value) {
    message.error('下载链接未就绪')
    return
  }
  // 触发下载（通过存储标识，实际下载由后端签名URL提供）
  message.info(`文档已就绪，存储标识：${exportStorageKey.value}`)
  emit('exported', exportStorageKey.value)
}

const handleCancel = () => {
  if (exporting.value && exportStatus.value !== 'done') {
    stopPolling()
  }
  emit('update:visible', false)
}

const handleClose = () => {
  emit('update:visible', false)
}

// 弹窗关闭时重置状态
watch(
  () => props.visible,
  (val) => {
    if (!val) {
      stopPolling()
      exporting.value = false
      exportStatus.value = 'pending'
      exportStorageKey.value = ''
      errorMessage.value = ''
    }
  },
)
</script>

<style scoped>
.export-modal__options {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.export-modal__section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.export-modal__section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #fff);
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color, #303030);
}

.export-modal__row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.export-modal__label {
  font-size: 13px;
  color: var(--text-secondary, #ccc);
  min-width: 70px;
}

.export-modal__progress {
  padding: 20px 0;
}

.export-modal__progress-text {
  text-align: center;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary, #ccc);
}

.export-modal__error {
  margin-top: 16px;
}

.export-modal__done {
  padding: 10px 0;
}
</style>
