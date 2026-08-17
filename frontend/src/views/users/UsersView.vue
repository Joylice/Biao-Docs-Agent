<template>
  <PageContainer
    title="用户管理"
    subtitle="角色细分：普通成员 / 资料库管理员 / 系统管理员"
  >
    <a-card class="users-card">
      <div class="users-toolbar">
        <a-input-search
          v-model:value="keyword"
          placeholder="按邮箱 / 姓名搜索"
          allow-clear
          style="width: 260px"
          @search="reload"
        />
        <a-select
          v-model:value="roleFilter"
          placeholder="角色筛选"
          allow-clear
          style="width: 160px"
          :options="roleOptions"
          @change="reload"
        />
      </div>

      <a-table
        :data-source="users"
        :columns="columns"
        :pagination="pagination"
        :loading="loading"
        row-key="id"
        size="middle"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'role'">
            <a-select
              :value="record.role"
              size="small"
              style="width: 140px"
              :options="roleOptions"
              @change="(val: UserRole) => handleRoleChange(record, val)"
            />
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
        </template>
      </a-table>
    </a-card>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import { fetchCurrentUserRole, type UserRole } from '@/stores/currentUser'

interface UserItem {
  id: string
  email: string
  display_name: string
  role: UserRole
  created_at: string
}

const roleOptions = [
  { value: 'member', label: '普通成员' },
  { value: 'kb_admin', label: '资料库管理员' },
  { value: 'admin', label: '系统管理员' },
]

const roleName: Record<string, string> = {
  member: '普通成员',
  kb_admin: '资料库管理员',
  admin: '系统管理员',
}

const columns = [
  { title: '邮箱', dataIndex: 'email', key: 'email' },
  { title: '姓名', dataIndex: 'display_name', key: 'display_name', width: 160 },
  { title: '角色', dataIndex: 'role', key: 'role', width: 170 },
  { title: '注册时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
]

const loading = ref(false)
const users = ref<UserItem[]>([])
const keyword = ref('')
const roleFilter = ref<UserRole | undefined>(undefined)

const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0,
  showTotal: (t: number) => `共 ${t} 条`,
})

const fetchUsers = async () => {
  loading.value = true
  try {
    const { data } = await api.get('/users', {
      params: {
        keyword: keyword.value.trim() || undefined,
        role: roleFilter.value || undefined,
        page: pagination.current,
        page_size: pagination.pageSize,
      },
    })
    if (data.code === 0) {
      users.value = data.data.items
      pagination.total = data.data.total
    }
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

const reload = () => {
  pagination.current = 1
  fetchUsers()
}

const handleRoleChange = (record: UserItem, newRole: UserRole) => {
  if (newRole === record.role) return
  Modal.confirm({
    title: `将「${record.display_name || record.email}」的角色变更为「${roleName[newRole]}」？`,
    content: '角色变更立即生效并写入审计日志。',
    okText: '确认变更',
    cancelText: '取消',
    onOk: async () => {
      try {
        const { data } = await api.put(`/users/${record.id}/role`, { role: newRole })
        if (data.code === 0) {
          message.success('角色已更新')
          fetchUsers()
          fetchCurrentUserRole() // 同步自身角色状态（后端禁止改自己，此处为兜底刷新）
        }
      } catch (e) {
        const err = e as { response?: { data?: { message?: string } } }
        message.error(err?.response?.data?.message || '角色变更失败')
        fetchUsers() // 回滚下拉框显示
      }
    },
  })
}

const handleTableChange = (pag: { current: number; pageSize: number }) => {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchUsers()
}

const formatTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(fetchUsers)
</script>

<style scoped>
.users-card {
  margin-bottom: 16px;
}
.users-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
