<template>
  <PageContainer
    title="用户管理"
    subtitle="角色细分：普通成员 / 资料库管理员 / 系统管理员；角色功能权限点可配置"
  >
    <a-card class="users-card">
      <a-tabs
        v-model:activeKey="activeTab"
        @change="handleTabChange"
      >
        <a-tab-pane
          key="users"
          tab="用户列表"
        >
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
            <a-button
              type="primary"
              class="users-toolbar__create"
              @click="formModalsRef?.openCreate()"
            >
              新建用户
            </a-button>
          </div>

          <a-table
            :data-source="users"
            :columns="columns"
            :pagination="pagination"
            :loading="loading"
            :scroll="{ x: 980 }"
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
                  @change="(val) => handleRoleChange(record as UserItem, val as UserRole)"
                />
              </template>
              <template v-else-if="column.key === 'created_at'">
                {{ formatTime(record.created_at) }}
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a @click="formModalsRef?.openEdit(record as UserItem)">编辑</a>
                  <a @click="resetPwdRef?.open(record as UserItem)">重置密码</a>
                  <a-tooltip
                    v-if="record.id === currentUserId"
                    title="不能删除自己"
                  >
                    <span class="action-disabled">删除</span>
                  </a-tooltip>
                  <a-popconfirm
                    v-else
                    :title="`删除用户「${record.display_name || record.email}」？`"
                    description="删除后该用户无法登录；名下有项目的用户不可删除，需先转移项目负责人。"
                    ok-text="确认删除"
                    cancel-text="取消"
                    :ok-button-props="{ danger: true }"
                    @confirm="handleDelete(record as UserItem)"
                  >
                    <a class="danger-link">删除</a>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane
          key="rbac"
          tab="角色权限"
        >
          <RbacMatrix ref="rbacRef" />
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <UserFormModals
      ref="formModalsRef"
      @created="reload"
      @updated="handleUserUpdated"
    />

    <ResetPasswordModal ref="resetPwdRef" />
  </PageContainer>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  fetchUsers as fetchUsersApi,
  updateUserRole,
  deleteUser,
} from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import { currentUserId, fetchCurrentUserRole, type UserRole } from '@/stores/currentUser'
import { roleOptions, roleName, errMsg, type UserItem } from './constants'
import UserFormModals from './components/UserFormModals.vue'
import ResetPasswordModal from './components/ResetPasswordModal.vue'
import RbacMatrix from './components/RbacMatrix.vue'

const activeTab = ref('users')

/* ---------------- Tab「用户列表」 ---------------- */

const columns = [
  { title: '邮箱', dataIndex: 'email', key: 'email', width: 260, fixed: 'left' as const },
  { title: '姓名', dataIndex: 'display_name', key: 'display_name', width: 160 },
  { title: '角色', dataIndex: 'role', key: 'role', width: 170 },
  { title: '注册时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'actions', width: 210 },
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

const formModalsRef = ref<InstanceType<typeof UserFormModals> | null>(null)
const resetPwdRef = ref<InstanceType<typeof ResetPasswordModal> | null>(null)
const rbacRef = ref<InstanceType<typeof RbacMatrix> | null>(null)

const fetchUsers = async () => {
  loading.value = true
  try {
    const { data } = await fetchUsersApi({
      keyword: keyword.value.trim() || undefined,
      role: roleFilter.value || undefined,
      page: pagination.current,
      page_size: pagination.pageSize,
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

/** 编辑弹窗保存成功：刷新列表并同步自身角色状态 */
const handleUserUpdated = () => {
  fetchUsers()
  fetchCurrentUserRole()
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
        const { data } = await updateUserRole(record.id, newRole)
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

const handleTableChange = (pag: { current?: number; pageSize?: number }) => {
  pagination.current = pag.current ?? 1
  pagination.pageSize = pag.pageSize ?? 10
  fetchUsers()
}

/** 删除用户（Popconfirm 轻量二次确认，无需填写理由；角色变更确认仍保留 Modal） */
const handleDelete = async (record: UserItem) => {
  try {
    const { data } = await deleteUser(record.id)
    if (data.code === 0) {
      message.success('用户已删除')
      fetchUsers()
    } else {
      message.error(data.message || '删除失败')
    }
  } catch (e) {
    message.error(errMsg(e, '删除用户失败'))
  }
}

const formatTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const handleTabChange = async (key: string | number) => {
  if (String(key) === 'rbac') {
    await nextTick()
    rbacRef.value?.loadIfNeeded()
  }
}

onMounted(fetchUsers)
</script>

<style scoped>
.users-card {
  margin-bottom: var(--space-4);
}
.users-toolbar {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.users-toolbar__create {
  margin-left: auto;
}
.danger-link {
  color: var(--color-error);
}
.action-disabled {
  color: var(--text-secondary);
  cursor: not-allowed;
}
</style>
