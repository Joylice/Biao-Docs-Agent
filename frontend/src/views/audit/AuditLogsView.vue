<template>
  <PageContainer
    title="审计日志"
    subtitle="关键操作留痕 · 追加式只读（who / what / when）"
  >
    <a-card class="audit-card">
      <div class="audit-toolbar">
        <a-input
          v-model:value="filters.action"
          placeholder="动作前缀（如 kb. / auth.）"
          allow-clear
          style="width: 200px"
          @press-enter="reload"
        />
        <a-input
          v-model:value="filters.targetType"
          placeholder="对象类型（如 document）"
          allow-clear
          style="width: 200px"
          @press-enter="reload"
        />
        <a-range-picker
          v-model:value="filters.range"
          show-time
          style="width: 360px"
        />
        <a-button
          type="primary"
          @click="reload"
        >
          查询
        </a-button>
        <a-button @click="resetFilters">
          重置
        </a-button>
      </div>

      <a-table
        :data-source="logs"
        :columns="columns"
        :pagination="pagination"
        :loading="loading"
        row-key="id"
        size="middle"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'user'">
            {{ record.user_name || record.user_id }}
          </template>
          <template v-else-if="column.key === 'action'">
            <a-tag :color="actionColor(record.action)">
              {{ record.action }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'target'">
            <span v-if="record.target_type">
              {{ record.target_type }}
              <span
                v-if="record.target_id"
                class="audit-target-id"
              >· {{ record.target_id }}</span>
            </span>
            <span
              v-else
              class="audit-muted"
            >—</span>
          </template>
          <template v-else-if="column.key === 'project_id'">
            <a-tooltip
              v-if="record.project_id"
              :title="record.project_id"
            >
              <span class="audit-target-id">{{ record.project_id.slice(0, 8) }}…</span>
            </a-tooltip>
            <span
              v-else
              class="audit-muted"
            >—</span>
          </template>
        </template>
        <template #expandedRowRender="{ record }">
          <pre class="audit-detail">{{ formatDetail(record.detail) }}</pre>
        </template>
      </a-table>
    </a-card>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import type { Dayjs } from 'dayjs'
import { fetchAuditLogs } from '@/api'
import PageContainer from '@/components/PageContainer.vue'

interface AuditItem {
  id: string
  user_id: string
  user_name: string
  action: string
  project_id: string | null
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

const columns = [
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
  { title: '用户', key: 'user', width: 140 },
  { title: '动作', dataIndex: 'action', key: 'action', width: 200 },
  { title: '对象', key: 'target', width: 220 },
  { title: '项目', dataIndex: 'project_id', key: 'project_id', width: 110 },
]

const loading = ref(false)
const logs = ref<AuditItem[]>([])

const filters = reactive<{
  action: string
  targetType: string
  range: [Dayjs, Dayjs] | null
}>({
  action: '',
  targetType: '',
  range: null,
})

const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showTotal: (t: number) => `共 ${t} 条`,
})

const fetchLogs = async () => {
  loading.value = true
  try {
    const params: {
      page: number
      page_size: number
      action?: string
      target_type?: string
      start?: string
      end?: string
    } = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    const action = filters.action.trim()
    if (action) params.action = action
    const targetType = filters.targetType.trim()
    if (targetType) params.target_type = targetType
    if (filters.range && filters.range.length === 2) {
      params.start = filters.range[0].toISOString()
      params.end = filters.range[1].toISOString()
    }
    const { data } = await fetchAuditLogs(params)
    if (data.code === 0) {
      logs.value = data.data.items
      pagination.total = data.data.total
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

const reload = () => {
  pagination.current = 1
  fetchLogs()
}

const resetFilters = () => {
  filters.action = ''
  filters.targetType = ''
  filters.range = null
  reload()
}

const actionColor = (action: string) => {
  if (action.startsWith('auth.')) return 'blue'
  if (action.startsWith('kb.')) return 'green'
  if (action.startsWith('user.')) return 'orange'
  if (action.startsWith('audit.')) return 'purple'
  return 'default'
}

const formatDetail = (detail: Record<string, unknown> | null) => {
  if (!detail || Object.keys(detail).length === 0) return '（无附加信息）'
  return JSON.stringify(detail, null, 2)
}

const handleTableChange = (pag: { current: number; pageSize: number }) => {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchLogs()
}

const formatTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

onMounted(fetchLogs)
</script>

<style scoped>
.audit-card {
  margin-bottom: 16px;
}
.audit-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.audit-target-id {
  color: var(--text-secondary);
  font-family: monospace;
}
.audit-muted {
  color: var(--text-secondary);
}
.audit-detail {
  margin: 0;
  padding: 8px 12px;
  background: var(--app-bg);
  border-radius: 6px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
}
</style>
