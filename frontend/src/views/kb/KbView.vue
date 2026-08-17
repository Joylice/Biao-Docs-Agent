<template>
  <div class="kb-view">
    <a-page-header
      title="资料库"
      sub-title="上传公司资料、案例、资质等素材"
    />

    <!-- 上传区域 -->
    <a-card class="mb-4">
      <a-upload-dragger
        :file-list="fileList"
        :before-upload="beforeUpload"
        :custom-request="handleUpload"
        multiple
        accept=".pdf,.doc,.docx"
      >
        <p class="ant-upload-drag-icon">
          <inbox-outlined />
        </p>
        <p class="ant-upload-text">
          点击或拖拽文件到此区域上传
        </p>
        <p class="ant-upload-hint">
          支持 PDF、Word 格式，单个文件不超过 50MB
        </p>
      </a-upload-dragger>
    </a-card>

    <!-- 文档列表 -->
    <a-card title="已上传文档">
      <a-table
        :columns="columns"
        :data-source="documents"
        :loading="loading"
        :pagination="{ pageSize: 10 }"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">
              {{ statusText(record.status) }}
            </a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-button
              size="small"
              type="link"
              @click="handleDelete(record)"
            >
              删除
            </a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { InboxOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import api from '@/api/client'

interface KbDocument {
  id: string
  title: string
  doc_type: string
  status: string
  created_at: string
}

const route = useRoute()
const projectId = route.params.projectId as string

const loading = ref(false)
const documents = ref<KbDocument[]>([])
const fileList = ref<UploadFile[]>([])

const columns = [
  { title: '文件名', dataIndex: 'title', key: 'title' },
  { title: '类型', dataIndex: 'doc_type', key: 'doc_type', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 80 },
]

const statusColor = (status: string) => {
  const colors: Record<string, string> = {
    uploaded: 'default',
    parsing: 'processing',
    parsed: 'blue',
    indexed: 'green',
    failed: 'red',
  }
  return colors[status] || 'default'
}

const statusText = (status: string) => {
  const texts: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '已解析',
    indexed: '已索引',
    failed: '失败',
  }
  return texts[status] || status
}

const fetchDocuments = async () => {
  loading.value = true
  try {
    const res = await api.get(`/projects/${projectId}/documents`, {
      params: { doc_type: 'kb_material' },
    })
    documents.value = res.data?.data?.items || res.data?.data || []
  } catch {
    message.error('获取文档列表失败')
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

const handleDelete = (record: KbDocument) => {
  message.info(`删除功能开发中: ${record.title}`)
}

onMounted(fetchDocuments)
</script>

<style scoped>
.kb-view { max-width: 1000px; }
.mb-4 { margin-bottom: 16px; }
</style>
