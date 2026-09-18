<template>
  <a-modal
    :open="visible"
    title="导出 Word 文档"
    :confirm-loading="exporting"
    ok-text="开始导出"
    cancel-text="取消"
    width="620px"
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

      <!-- 格式要求（自定义覆盖，留空则用招标解析默认值） -->
      <div class="export-modal__section">
        <div class="export-modal__section-title">
          格式要求
          <span class="export-modal__hint">留空则沿用招标文件解析的默认值</span>
        </div>
        <div class="export-modal__grid">
          <div class="export-modal__field">
            <label class="export-modal__label">正文字体</label>
            <a-select
              v-model:value="formatOverride.body_font"
              size="small"
              allow-clear
              placeholder="默认"
              :options="fontOptions"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">正文字号</label>
            <a-select
              v-model:value="formatOverride.body_size_pt"
              size="small"
              allow-clear
              placeholder="默认"
              :options="fontSizeOptions"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">标题字号</label>
            <a-select
              v-model:value="formatOverride.heading_size_pt"
              size="small"
              allow-clear
              placeholder="默认"
              :options="fontSizeOptions"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">行距</label>
            <a-select
              v-model:value="lineSpacingPreset"
              size="small"
              allow-clear
              placeholder="默认"
              :options="lineSpacingOptions"
            />
          </div>
        </div>
        <div class="export-modal__grid">
          <div class="export-modal__field">
            <label class="export-modal__label">上边距 (cm)</label>
            <a-input-number
              v-model:value="marginsInput.top"
              size="small"
              :min="0"
              :max="10"
              :step="0.1"
              placeholder="默认"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">下边距 (cm)</label>
            <a-input-number
              v-model:value="marginsInput.bottom"
              size="small"
              :min="0"
              :max="10"
              :step="0.1"
              placeholder="默认"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">左边距 (cm)</label>
            <a-input-number
              v-model:value="marginsInput.left"
              size="small"
              :min="0"
              :max="10"
              :step="0.1"
              placeholder="默认"
            />
          </div>
          <div class="export-modal__field">
            <label class="export-modal__label">右边距 (cm)</label>
            <a-input-number
              v-model:value="marginsInput.right"
              size="small"
              :min="0"
              :max="10"
              :step="0.1"
              placeholder="默认"
            />
          </div>
        </div>
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
import { ref, computed, watch, reactive } from 'vue'
import { message } from 'ant-design-vue'
import { DownloadOutlined } from '@ant-design/icons-vue'
import { fetchWorkflowExport } from '@/api'
import type { ExportOptions, FormatOverride } from '@/types'

const props = defineProps<{
  visible: boolean
  projectId: string
  currentChapter?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'exported', storageKey: string): void
}>()

/* ---------------- UI 选项状态 ---------------- */
const options = reactive({
  includeToc: true,
  includeAnnotations: false,
  includeHeaderFooter: true,
  paperSize: 'A4' as 'A4' | 'A3',
  orientation: 'portrait' as 'portrait' | 'landscape',
  scope: 'all' as 'all' | 'current',
})

/* ---------------- 格式覆盖状态 ---------------- */
const formatOverride = reactive<FormatOverride>({})

/** 行距预设（前端选值，提交时映射到 FormatOverride 的 line_spacing / line_spacing_fixed_pt） */
const lineSpacingPreset = ref<string | undefined>(undefined)

/** 页边距输入（单独收集，提交时合并到 FormatOverride.margins_cm） */
const marginsInput = reactive<{ top?: number; bottom?: number; left?: number; right?: number }>({})

/* ---------------- 下拉选项 ---------------- */
const fontOptions = [
  { label: '宋体', value: '宋体' },
  { label: '仿宋', value: '仿宋' },
  { label: '黑体', value: '黑体' },
  { label: '楷体', value: '楷体' },
  { label: '微软雅黑', value: '微软雅黑' },
  { label: 'Times New Roman', value: 'Times New Roman' },
]

const fontSizeOptions = [
  { label: '三号 (16pt)', value: 16 },
  { label: '小三 (15pt)', value: 15 },
  { label: '四号 (14pt)', value: 14 },
  { label: '小四 (12pt)', value: 12 },
  { label: '五号 (10.5pt)', value: 10.5 },
]

const lineSpacingOptions = [
  { label: '单倍行距', value: '1.0' },
  { label: '1.15倍行距', value: '1.15' },
  { label: '1.5倍行距', value: '1.5' },
  { label: '2.0倍行距', value: '2.0' },
  { label: '固定值 28磅', value: 'fixed_28' },
]

/* ---------------- 导出状态 ---------------- */
const exporting = ref(false)
const exportStatus = ref<'pending' | 'running' | 'done' | 'failed'>('pending')
const exportStorageKey = ref('')
const downloadUrl = ref('')
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

/* ---------------- 构建导出参数 ---------------- */
const buildExportOptions = (): ExportOptions => {
  // 格式覆盖：只收集非空字段
  const override: FormatOverride = {}
  if (formatOverride.body_font) override.body_font = formatOverride.body_font
  if (formatOverride.body_size_pt != null) override.body_size_pt = formatOverride.body_size_pt
  if (formatOverride.heading_size_pt != null) override.heading_size_pt = formatOverride.heading_size_pt

  // 行距映射
  if (lineSpacingPreset.value) {
    if (lineSpacingPreset.value === 'fixed_28') {
      override.line_spacing_fixed_pt = 28
    } else {
      override.line_spacing = parseFloat(lineSpacingPreset.value)
    }
  }

  // 页边距：仅收集有值的边
  const margins: NonNullable<FormatOverride['margins_cm']> = {}
  let hasMargin = false
  if (marginsInput.top != null) { margins.top = marginsInput.top; hasMargin = true }
  if (marginsInput.bottom != null) { margins.bottom = marginsInput.bottom; hasMargin = true }
  if (marginsInput.left != null) { margins.left = marginsInput.left; hasMargin = true }
  if (marginsInput.right != null) { margins.right = marginsInput.right; hasMargin = true }
  if (hasMargin) override.margins_cm = margins

  return {
    include_toc: options.includeToc,
    include_annotations: options.includeAnnotations,
    include_header_footer: options.includeHeaderFooter,
    paper_size: options.paperSize,
    orientation: options.orientation,
    scope: options.scope,
    current_chapter: options.scope === 'current' ? props.currentChapter : undefined,
    format_override: Object.keys(override).length > 0 ? override : undefined,
  }
}

/* ---------------- 导出 ---------------- */
/** 存在未确认高风险废标条款时提示（2026-09-03 门禁降级：后端警告放行不阻塞） */
const warnUnconfirmed = (data: Record<string, unknown> | undefined) => {
  const n = Number(data?.unconfirmed_high ?? 0)
  if (n > 0) {
    message.warning(`存在 ${n} 条未确认的高风险废标条款，本次导出已放行，建议先前往招标解析页完成人工确认`)
  }
}

const handleExport = async () => {
  exporting.value = true
  exportStatus.value = 'pending'
  errorMessage.value = ''

  try {
    const payload = buildExportOptions()
    const res = await fetchWorkflowExport(props.projectId, payload)
    const data = res.data?.data
    exportStatus.value = (data?.export_status as 'pending' | 'running' | 'done' | 'failed') || 'pending'
    exportStorageKey.value = data?.export_storage_key || ''
    downloadUrl.value = data?.download_url || ''

    if (exportStatus.value === 'done') {
      warnUnconfirmed(data)
      message.success('导出成功')
      return
    }

    // 轮询导出状态
    exportStatus.value = 'running'
    let attempts = 0
    pollTimer = window.setInterval(async () => {
      attempts += 1
      try {
        const pollRes = await fetchWorkflowExport(props.projectId, payload)
        const pollData = pollRes.data?.data
        if (pollData?.export_status === 'done') {
          exportStatus.value = 'done'
          exportStorageKey.value = pollData.export_storage_key || ''
          downloadUrl.value = pollData.download_url || ''
          stopPolling()
          warnUnconfirmed(pollData)
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

/* ---------------- 下载 ---------------- */
const handleDownload = () => {
  if (downloadUrl.value) {
    // 后端返回预签名 URL，直接打开下载
    window.open(downloadUrl.value, '_blank')
    emit('exported', exportStorageKey.value)
    return
  }
  if (!exportStorageKey.value) {
    message.error('下载链接未就绪')
    return
  }
  // 兜底：仅有 storage_key 时通知父组件
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

/* ---------------- 弹窗关闭时重置状态 ---------------- */
watch(
  () => props.visible,
  (val) => {
    if (!val) {
      stopPolling()
      exporting.value = false
      exportStatus.value = 'pending'
      exportStorageKey.value = ''
      downloadUrl.value = ''
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
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.export-modal__hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-tertiary, #888);
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

.export-modal__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
}

.export-modal__field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.export-modal__field .export-modal__label {
  min-width: 80px;
  flex-shrink: 0;
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
