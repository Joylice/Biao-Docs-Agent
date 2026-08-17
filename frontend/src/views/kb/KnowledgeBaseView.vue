<template>
  <div class="kb-view">
    <PageContainer
      title="资料库"
      subtitle="上传与管理公司资料（产品手册/历史方案/资质证书），用于方案生成的检索引用"
    >
      <!-- 资料库空态提示条 -->
      <a-alert
        v-if="documents.length === 0 && !loading && !loadError"
        type="info"
        show-icon
        class="mb-4"
        message="资料库为空：上传公司资料（产品手册/历史方案/资质证书）后，方案生成与检索测试才能引用"
      />

      <!-- 拖拽上传 -->
      <a-card
        :bordered="false"
        class="mb-4"
      >
        <a-upload-dragger
          v-model:file-list="uploadList"
          :multiple="true"
          accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
          :before-upload="beforeUpload"
          :custom-request="handleUpload"
          :show-upload-list="true"
        >
          <p class="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p class="ant-upload-text">
            点击或拖拽文件到此区域上传
          </p>
          <p class="ant-upload-hint">
            支持 PDF / Word / 图片格式，单文件不超过 50MB，上传后自动解析并建立索引
          </p>
        </a-upload-dragger>
      </a-card>

      <!-- 文件列表 -->
      <a-card
        title="已上传资料"
        class="mb-4"
      >
        <template #extra>
          <a-button
            size="small"
            @click="fetchDocuments"
          >
            刷新
          </a-button>
        </template>
        <LoadingSkeleton
          v-if="loading"
          :rows="4"
        />
        <ErrorState
          v-else-if="loadError"
          :description="loadError"
        >
          <template #action>
            <a-button
              type="primary"
              @click="fetchDocuments"
            >
              重试
            </a-button>
          </template>
        </ErrorState>
        <EmptyState
          v-else-if="documents.length === 0"
          description="暂无资料，上传后可在方案生成时检索引用"
        />
        <a-table
          v-else
          :columns="columns"
          :data-source="documents"
          :pagination="{ pageSize: 10, showTotal: (t: number) => `共 ${t} 条` }"
          :scroll="{ x: 700 }"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'title'">
              <div class="doc-title">
                <component
                  :is="docTypeIcon(record.title)"
                  class="doc-title__icon"
                />
                <span class="doc-title__name">{{ record.title }}</span>
              </div>
            </template>
            <template v-if="column.key === 'status'">
              <div class="doc-status">
                <a-tag :color="statusColor(record.status)">
                  {{ statusText(record.status) }}
                </a-tag>
                <!-- 索引中：后端暂无 progress 字段，用不定进度条占位（待后端补充） -->
                <a-progress
                  v-if="record.status === 'parsing' || record.status === 'indexing'"
                  :percent="60"
                  status="active"
                  size="small"
                  class="doc-status__progress"
                />
              </div>
            </template>
            <template v-if="column.key === 'created_at'">
              {{ formatTime(record.created_at) }}
            </template>
            <template v-if="column.key === 'action'">
              <a-space>
                <a-button
                  v-if="record.status === 'failed'"
                  size="small"
                  type="link"
                  @click="handleRetry(record)"
                >
                  重试
                </a-button>
                <a-button
                  size="small"
                  type="link"
                  danger
                  @click="handleDelete(record)"
                >
                  删除
                </a-button>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-card>

      <!-- 检索测试 -->
      <a-card title="检索测试">
        <template #extra>
          <a-tag color="blue">
            RAG 验证
          </a-tag>
        </template>
        <a-input-search
          v-model:value="searchQuery"
          placeholder="输入检索内容，验证资料库命中效果（如：公司资质、产品参数）"
          enter-button="检索"
          :loading="searching"
          class="mb-4"
          @search="handleSearch"
        />
        <LoadingSkeleton
          v-if="searching"
          :rows="3"
        />
        <EmptyState
          v-else-if="searched && results.length === 0"
          description="无命中结果，尝试调整检索词或先上传资料"
        />
        <a-list
          v-else-if="results.length > 0"
          :data-source="results"
          size="small"
          class="search-results"
        >
          <template #renderItem="{ item }">
            <a-list-item class="search-result">
              <div class="search-result__main">
                <div class="search-result__header">
                  <a-tag
                    :color="similarityColor(item.score)"
                    class="search-result__score"
                  >
                    相关度 {{ item.score.toFixed(4) }}
                  </a-tag>
                  <span class="search-result__title">{{ item.title || '未知文档' }}</span>
                  <span
                    v-if="item.page_no != null"
                    class="search-result__page"
                  >
                    第 {{ item.page_no }} 页
                  </span>
                </div>
                <div class="search-result__content">
                  {{ item.content }}
                </div>
              </div>
            </a-list-item>
          </template>
        </a-list>
        <EmptyState
          v-else
          description="输入关键词验证资料库检索效果"
        />
      </a-card>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  FileImageOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  InboxOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

interface KbDocument {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
}

interface SearchResult {
  chunk_id: string
  doc_id: string
  title?: string
  content: string
  page_no: number | null
  score: number
}

const route = useRoute()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
const documents = ref<KbDocument[]>([])
const uploadList = ref<UploadFile[]>([])

const columns = [
  { title: '文件名', dataIndex: 'title', key: 'title' },
  { title: '状态', key: 'status', width: 140 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 130 },
]

/** 按文件扩展名映射类型图标（title 为文件名，如 xx.pdf / xx.docx） */
const docTypeIcon = (title: string) => {
  const ext = (title.split('.').pop() || '').toLowerCase()
  if (ext === 'pdf') return FilePdfOutlined
  if (['doc', 'docx', 'word'].includes(ext)) return FileWordOutlined
  if (['jpg', 'jpeg', 'png', 'gif'].includes(ext)) return FileImageOutlined
  return FileOutlined
}

const statusColor = (status: string): string => {
  const colors: Record<string, string> = {
    uploaded: 'default',
    parsing: 'processing',
    indexing: 'processing',
    parsed: 'blue',
    indexed: 'green',
    failed: 'red',
  }
  return colors[status] || 'default'
}

const statusText = (status: string): string => {
  const texts: Record<string, string> = {
    uploaded: '已上传',
    parsing: '索引中',
    indexing: '索引中',
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

const fetchDocuments = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.get(`/projects/${projectId}/documents`, {
      params: { doc_type: 'kb_material' },
    })
    documents.value = res.data?.data?.items || res.data?.data || []
  } catch {
    loadError.value = '获取文档列表失败'
  } finally {
    loading.value = false
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
    const res = await api.post(
      `/projects/${projectId}/documents`,
      formData,
      {
        params: { doc_type: 'kb_material' },
        onUploadProgress: (e) => {
          if (e.total) {
            options.onProgress?.({ percent: Math.round((e.loaded / e.total) * 100) })
          }
        },
      }
    )
    options.onSuccess?.(res.data)
    message.success(`${file.name} 上传成功`)
    fetchDocuments()
  } catch (err) {
    options.onError?.(err as Error)
    message.error(`${file.name} 上传失败`)
  }
}

const handleRetry = (record: KbDocument) => {
  message.info(`后端暂未提供失败重试接口（${record.title}），请重新上传该文件`)
}

const handleDelete = (record: KbDocument) => {
  message.info(`删除功能开发中: ${record.title}`)
}

/* ---------------- 检索测试 ---------------- */
const searchQuery = ref('')
const searching = ref(false)
const searched = ref(false)
const results = ref<SearchResult[]>([])

const similarityColor = (score: number): string => {
  if (score >= 0.6) return 'green'
  if (score >= 0.3) return 'blue'
  return 'default'
}

const handleSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) {
    message.warning('请输入检索内容')
    return
  }
  searching.value = true
  searched.value = true
  try {
    const res = await api.get(`/projects/${projectId}/kb/search`, {
      params: { q, top_k: 5 },
    })
    results.value = res.data?.data?.items || []
  } catch {
    message.error('检索失败')
  } finally {
    searching.value = false
  }
}

onMounted(fetchDocuments)
</script>

<style scoped>
.kb-view { max-width: 1000px; }
.mb-4 { margin-bottom: 16px; }

.doc-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.doc-title__icon {
  color: var(--color-primary);
  font-size: 16px;
  flex-shrink: 0;
}

.doc-title__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-status__progress {
  width: 96px;
  margin-left: 8px;
  display: inline-block;
  vertical-align: middle;
}

.search-results {
  background: var(--card-bg);
}

.search-result__main {
  width: 100%;
  min-width: 0;
}

.search-result__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.search-result__title {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-result__page {
  color: var(--text-secondary, #999);
  font-size: 12px;
  flex-shrink: 0;
}

.search-result__content {
  font-size: 13px;
  color: var(--text-secondary, #666);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
