<template>
  <!-- 资料列表 -->
  <a-card
    title="全部资料"
    class="kb-card"
  >
    <!-- 三期 S2：分类 / 标签筛选 -->
    <template #extra>
      <a-space>
        <a-select
          v-model:value="filterCategory"
          placeholder="全部分类"
          allow-clear
          style="width: 140px"
          :options="categoryOptions"
          @change="handleFilterChange"
        />
        <a-input
          v-model:value="filterTag"
          placeholder="按标签筛选"
          allow-clear
          style="width: 160px"
          @press-enter="onTagFilterEnter"
          @change="onTagInputChange"
        />
      </a-space>
    </template>

    <EmptyState
      v-if="!loading && materials.length === 0"
      illustration="box"
      description="还没有资料，点击右上角「上传资料」开始建设素材库"
    />
    <LoadingSkeleton
      v-else-if="loading"
      :rows="4"
    />
    <a-table
      v-else
      :data-source="materials"
      :columns="columns"
      :pagination="pagination"
      :scroll="{ x: 1060 }"
      row-key="id"
      size="middle"
      @change="handleTableChange"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'file'">
          <FileTextOutlined class="kb-file-icon" />
          <a-tooltip :title="record.title">
            <span class="kb-file-name">{{ record.title }}</span>
          </a-tooltip>
        </template>
        <template v-else-if="column.key === 'category'">
          <a-tag
            v-if="record.category"
            color="geekblue"
          >
            {{ categoryLabel(record.category) }}
          </a-tag>
          <span
            v-else
            class="kb-muted"
          >未分类</span>
        </template>
        <template v-else-if="column.key === 'tags'">
          <template v-if="record.tags?.length">
            <a-tag
              v-for="tag in record.tags"
              :key="tag"
              class="kb-tag"
            >
              {{ tag }}
            </a-tag>
          </template>
          <span
            v-else
            class="kb-muted"
          >—</span>
        </template>
        <template v-else-if="column.key === 'uploader_name'">
          {{ record.uploader_name || '—' }}
        </template>
        <template v-else-if="column.key === 'status'">
          <a-badge
            :status="statusMeta[record.status]?.badge ?? 'default'"
            :text="statusMeta[record.status]?.text ?? record.status"
          />
        </template>
        <template v-else-if="column.key === 'created_at'">
          {{ formatTime(record.created_at) }}
        </template>
        <template v-else-if="column.key === 'action'">
          <!-- 阶段 2：下载所有登录用户可用 -->
          <a-button
            type="link"
            size="small"
            :loading="downloadingId === record.id"
            @click="handleDownload(record as Material)"
          >
            下载
          </a-button>
          <!-- 编辑/删除：资料库管理员或上传者本人 -->
          <template v-if="canEditMaterial(record.uploader_id)">
            <a-button
              type="link"
              size="small"
              @click="emit('edit', record as Material)"
            >
              编辑
            </a-button>
            <a-popconfirm
              title="删除该资料？"
              description="删除后不可恢复，已挂载到项目方案的素材将无法检索。"
              ok-text="删除"
              cancel-text="取消"
              :ok-button-props="{ danger: true }"
              @confirm="handleDelete(record as Material)"
            >
              <a-button
                type="link"
                danger
                size="small"
              >
                删除
              </a-button>
            </a-popconfirm>
          </template>
        </template>
      </template>
    </a-table>
  </a-card>
</template>

<script setup lang="ts">
import { onUnmounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { FileTextOutlined } from '@ant-design/icons-vue'
import {
  fetchMaterials as fetchMaterialsApi,
  deleteMaterial,
  downloadMaterial,
  type MaterialListParams,
} from '@/api'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { usePermission } from '@/composables/usePermission'
import { debounce } from '@/utils/debounce'
import { categoryOptions, categoryLabel, type Material } from '../constants'

const props = defineProps<{
  selectedKbId: string
}>()

const emit = defineEmits<{
  (e: 'edit', record: Material): void
}>()

const { canEditMaterial } = usePermission()

const statusMeta: Record<string, { badge: 'default' | 'processing' | 'success' | 'error'; text: string }> = {
  uploaded: { badge: 'default', text: '待处理' },
  indexing: { badge: 'processing', text: '索引中' },
  indexed: { badge: 'success', text: '已完成' },
  failed: { badge: 'error', text: '失败' },
}

const columns = [
  { title: '文件', key: 'file', dataIndex: 'title', width: 220, fixed: 'left' as const },
  { title: '分类', key: 'category', dataIndex: 'category', width: 110 },
  { title: '标签', key: 'tags', dataIndex: 'tags', width: 180 },
  { title: '上传者', key: 'uploader_name', dataIndex: 'uploader_name', width: 100 },
  { title: '状态', key: 'status', dataIndex: 'status', width: 110 },
  { title: '上传时间', key: 'created_at', dataIndex: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 180 },
]

const loading = ref(false)
const downloadingId = ref('')
const materials = ref<Material[]>([])

// 三期 S2：筛选状态
const filterCategory = ref<string | undefined>(undefined)
const filterTag = ref('')

const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0,
  showTotal: (t: number) => `共 ${t} 条`,
})

const fetchMaterials = async () => {
  loading.value = true
  try {
    const params: MaterialListParams = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filterCategory.value) params.category = filterCategory.value
    const tag = filterTag.value.trim()
    if (tag) params.tag = tag
    if (props.selectedKbId) params.kb_id = props.selectedKbId
    const { data } = await fetchMaterialsApi(params)
    if (data.code === 0) {
      materials.value = data.data.items
      pagination.total = data.data.total
    }
  } catch {
    message.error('加载资料失败')
  } finally {
    loading.value = false
  }
}

const handleFilterChange = () => {
  pagination.current = 1
  fetchMaterials()
}

/** 标签筛选输入防抖（沿用 500ms；回车立即过滤） */
const debouncedTagFilter = debounce(handleFilterChange, 500)
const onTagInputChange = () => {
  debouncedTagFilter()
}
const onTagFilterEnter = () => {
  debouncedTagFilter.cancel()
  handleFilterChange()
}

/** 阶段 2：下载素材（后端代理字节流 → blob 保存本地） */
const handleDownload = async (record: Material) => {
  downloadingId.value = record.id
  try {
    const resp = await downloadMaterial(record.id)
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = record.title || '素材'
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error('下载失败，请重试')
  } finally {
    downloadingId.value = ''
  }
}

/** 删除资料（Popconfirm 二次确认，无需填写理由） */
const handleDelete = async (record: Material) => {
  try {
    const { data } = await deleteMaterial(record.id)
    if (data.code === 0) {
      message.success('已删除')
      fetchMaterials()
    }
  } catch {
    message.error('删除失败')
  }
}

const handleTableChange = (pag: { current?: number; pageSize?: number }) => {
  pagination.current = pag.current ?? 1
  pagination.pageSize = pag.pageSize ?? 10
  fetchMaterials()
}

const formatTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 保持当前分页刷新（删除知识库后沿用） */
const fetch = () => {
  fetchMaterials()
}

/** 重置到第 1 页并刷新（切换知识库 / 上传成功后沿用） */
const refresh = () => {
  pagination.current = 1
  fetchMaterials()
}

defineExpose({ fetch, refresh })

onUnmounted(() => {
  debouncedTagFilter.cancel()
})
</script>

<style scoped>
.kb-card {
  margin-bottom: var(--space-4);
}
.kb-file-icon {
  color: var(--color-primary);
  margin-right: var(--space-2);
}
.kb-file-name {
  max-width: 360px;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.kb-tag {
  margin-bottom: 2px;
}
.kb-muted {
  color: var(--text-secondary);
}
</style>
