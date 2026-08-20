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
              @click="openCreate"
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
                  @change="(val: UserRole) => handleRoleChange(record, val)"
                />
              </template>
              <template v-else-if="column.key === 'created_at'">
                {{ formatTime(record.created_at) }}
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a @click="openEdit(record)">编辑</a>
                  <a @click="openResetPwd(record)">重置密码</a>
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
                    @confirm="handleDelete(record)"
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
          <p class="rbac-hint">
            勾选即授予、取消即回收，变更立即全量覆盖保存并写入审计日志。
          </p>
          <a-table
            :data-source="roleRows"
            :columns="rbacColumns"
            :loading="rbacLoading"
            :pagination="false"
            row-key="role"
            size="middle"
            :scroll="{ x: 'max-content' }"
          >
            <template #headerCell="{ column }">
              <div
                v-if="permByCode[column.key]"
                class="rbac-col-head"
              >
                <a-tag
                  v-if="groupStartCodes.has(column.key)"
                  class="rbac-col-head__tag"
                >
                  {{ categoryLabel(permByCode[column.key].category) }}
                </a-tag>
                <div class="rbac-col-head__name">
                  {{ permByCode[column.key].name }}
                </div>
                <div class="rbac-col-head__code">
                  {{ column.key }}
                </div>
              </div>
              <template v-else>
                {{ column.title }}
              </template>
            </template>
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'role'">
                <div class="rbac-role-cell">
                  <span>{{ roleName[record.role] }}</span>
                  <span class="rbac-role-cell__code">{{ record.role }}</span>
                </div>
              </template>
              <template v-else>
                <a-tooltip
                  v-if="lockReason(record.role, column.key)"
                  :title="lockReason(record.role, column.key)"
                >
                  <span class="rbac-check">
                    <a-checkbox
                      :checked="roleCodes[record.role as UserRole].includes(column.key)"
                      disabled
                    />
                  </span>
                </a-tooltip>
                <a-checkbox
                  v-else
                  :checked="roleCodes[record.role as UserRole].includes(column.key)"
                  :disabled="savingRoles[record.role as UserRole]"
                  @change="onPermChange($event, record.role, column.key)"
                />
              </template>
            </template>
          </a-table>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-modal
      v-model:open="createOpen"
      title="新建用户"
      ok-text="创建"
      cancel-text="取消"
      :confirm-loading="createSubmitting"
      @ok="submitCreate"
    >
      <a-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        layout="vertical"
      >
        <a-form-item
          label="邮箱"
          name="email"
        >
          <a-input
            v-model:value="createForm.email"
            placeholder="user@example.com"
          />
        </a-form-item>
        <a-form-item
          label="姓名"
          name="display_name"
        >
          <a-input v-model:value="createForm.display_name" />
        </a-form-item>
        <a-form-item
          label="初始密码"
          name="password"
        >
          <a-input-password v-model:value="createForm.password" />
        </a-form-item>
        <a-form-item
          label="角色"
          name="role"
        >
          <a-select
            v-model:value="createForm.role"
            :options="roleOptions"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="editOpen"
      title="编辑用户"
      ok-text="保存"
      cancel-text="取消"
      :confirm-loading="editSubmitting"
      @ok="submitEdit"
    >
      <a-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        layout="vertical"
      >
        <a-form-item
          label="姓名"
          name="display_name"
        >
          <a-input v-model:value="editForm.display_name" />
        </a-form-item>
        <a-form-item
          label="角色"
          name="role"
        >
          <a-select
            v-model:value="editForm.role"
            :options="roleOptions"
            :disabled="editIsSelf"
          />
          <div
            v-if="editIsSelf"
            class="form-hint"
          >
            不能变更自己的角色
          </div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="resetPwdOpen"
      title="重置密码"
      ok-text="重置"
      cancel-text="取消"
      :confirm-loading="resetPwdSubmitting"
      @ok="submitResetPwd"
    >
      <p class="form-hint">
        正在重置「{{ resetPwdTarget?.display_name || resetPwdTarget?.email }}」的密码
      </p>
      <a-form
        ref="resetPwdFormRef"
        :model="resetPwdForm"
        :rules="resetPwdRules"
        layout="vertical"
      >
        <a-form-item
          label="新密码"
          name="password"
        >
          <a-input-password v-model:value="resetPwdForm.password" />
        </a-form-item>
      </a-form>
    </a-modal>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message, Modal, type FormInstance } from 'ant-design-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import { currentUserId, fetchCurrentUserRole, type UserRole } from '@/stores/currentUser'

interface UserItem {
  id: string
  email: string
  display_name: string
  role: UserRole
  created_at: string
}

/** 权限点目录项（GET /rbac/permissions） */
interface PermItem {
  code: string
  name: string
  category: string
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

const errMsg = (e: unknown, fallback: string) => {
  const err = e as { response?: { data?: { message?: string } } }
  return err?.response?.data?.message || fallback
}

/* ---------------- 阶段4：新建 / 编辑 / 重置密码 / 删除 ---------------- */

const createOpen = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({ email: '', display_name: '', password: '', role: 'member' as UserRole })
const createRules = {
  email: [
    { required: true, message: '请输入邮箱' },
    { type: 'email' as const, message: '邮箱格式不正确' },
  ],
  display_name: [{ required: true, message: '请输入姓名' }],
  password: [
    { required: true, message: '请输入初始密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
}

const openCreate = () => {
  createForm.email = ''
  createForm.display_name = ''
  createForm.password = ''
  createForm.role = 'member'
  createOpen.value = true
}

const submitCreate = async () => {
  await createFormRef.value?.validate()
  createSubmitting.value = true
  try {
    const { data } = await api.post('/users', { ...createForm })
    if (data.code === 0) {
      message.success('用户已创建')
      createOpen.value = false
      reload()
    } else {
      message.error(data.message || '创建失败')
    }
  } catch (e) {
    message.error(errMsg(e, '创建用户失败'))
  } finally {
    createSubmitting.value = false
  }
}

const editOpen = ref(false)
const editSubmitting = ref(false)
const editFormRef = ref<FormInstance>()
const editTarget = ref<UserItem | null>(null)
const editForm = reactive({ display_name: '', role: 'member' as UserRole })
const editRules = {
  display_name: [{ required: true, message: '请输入姓名' }],
}
const editIsSelf = computed(() => editTarget.value?.id === currentUserId.value)

const openEdit = (record: UserItem) => {
  editTarget.value = record
  editForm.display_name = record.display_name
  editForm.role = record.role
  editOpen.value = true
}

const submitEdit = async () => {
  await editFormRef.value?.validate()
  if (!editTarget.value) return
  editSubmitting.value = true
  try {
    const body: { display_name: string; role?: UserRole } = {
      display_name: editForm.display_name,
    }
    if (!editIsSelf.value) body.role = editForm.role
    const { data } = await api.patch(`/users/${editTarget.value.id}`, body)
    if (data.code === 0) {
      message.success('用户已更新')
      editOpen.value = false
      fetchUsers()
      fetchCurrentUserRole()
    } else {
      message.error(data.message || '更新失败')
    }
  } catch (e) {
    message.error(errMsg(e, '更新用户失败'))
  } finally {
    editSubmitting.value = false
  }
}

const resetPwdOpen = ref(false)
const resetPwdSubmitting = ref(false)
const resetPwdFormRef = ref<FormInstance>()
const resetPwdTarget = ref<UserItem | null>(null)
const resetPwdForm = reactive({ password: '' })
const resetPwdRules = {
  password: [
    { required: true, message: '请输入新密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
}

const openResetPwd = (record: UserItem) => {
  resetPwdTarget.value = record
  resetPwdForm.password = ''
  resetPwdOpen.value = true
}

const submitResetPwd = async () => {
  await resetPwdFormRef.value?.validate()
  if (!resetPwdTarget.value) return
  resetPwdSubmitting.value = true
  try {
    const { data } = await api.put(`/users/${resetPwdTarget.value.id}/password`, {
      password: resetPwdForm.password,
    })
    if (data.code === 0) {
      message.success('密码已重置')
      resetPwdOpen.value = false
    } else {
      message.error(data.message || '重置失败')
    }
  } catch (e) {
    message.error(errMsg(e, '重置密码失败'))
  } finally {
    resetPwdSubmitting.value = false
  }
}

/** 删除用户（Popconfirm 轻量二次确认，无需填写理由；角色变更确认仍保留 Modal） */
const handleDelete = async (record: UserItem) => {
  try {
    const { data } = await api.delete(`/users/${record.id}`)
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

/* ---------------- Tab「角色权限」（阶段 A：角色权限配置矩阵） ---------------- */

/** 矩阵行：三个角色 */
const roleRows: { role: UserRole }[] = [
  { role: 'member' },
  { role: 'kb_admin' },
  { role: 'admin' },
]

/** category 分组标签（后端返回英文分类，此处仅做展示文案映射） */
const CATEGORY_LABELS: Record<string, string> = {
  system: '系统',
  kb: '资料库',
  settings: '模型设置',
  project: '项目',
}

const categoryLabel = (category: string) => CATEGORY_LABELS[category] || category

const rbacLoading = ref(false)
const rbacLoaded = ref(false)
const permCatalog = ref<PermItem[]>([])
const roleCodes = reactive<Record<UserRole, string[]>>({
  member: [],
  kb_admin: [],
  admin: [],
})
const savingRoles = reactive<Record<UserRole, boolean>>({
  member: false,
  kb_admin: false,
  admin: false,
})

/** 按 category 首次出现顺序分组排序（后端目录本身已按类聚集，此处兜底） */
const sortedCatalog = computed(() => {
  const order: string[] = []
  for (const item of permCatalog.value) {
    if (!order.includes(item.category)) order.push(item.category)
  }
  return [...permCatalog.value].sort(
    (a, b) => order.indexOf(a.category) - order.indexOf(b.category),
  )
})

/** 每个 category 分组的首个权限码（列头打分组标签） */
const groupStartCodes = computed(() => {
  const seen = new Set<string>()
  const starts = new Set<string>()
  for (const item of sortedCatalog.value) {
    if (!seen.has(item.category)) {
      seen.add(item.category)
      starts.add(item.code)
    }
  }
  return starts
})

const permByCode = computed(() => {
  const map: Record<string, PermItem> = {}
  for (const item of permCatalog.value) {
    map[item.code] = item
  }
  return map
})

const rbacColumns = computed(() => [
  { title: '角色', key: 'role', width: 180 },
  ...sortedCatalog.value.map((item) => ({
    title: item.name,
    key: item.code,
    align: 'center' as const,
    width: 150,
  })),
])

/** 复选框锁定原因（前端防呆；后端另有兜底校验） */
const lockReason = (role: UserRole, code: string): string => {
  if (code === 'project:member_manage') return 'owner 数据属性，不可授予'
  if (role === 'admin' && code === 'system:manage') {
    return '防自我锁死：系统管理员必须保留 system:manage'
  }
  return ''
}

const fetchRoleCodes = async (role: UserRole) => {
  const { data } = await api.get(`/rbac/roles/${role}/permissions`)
  if (data.code === 0) {
    roleCodes[role] = data.data.codes
  }
}

const fetchRbac = async () => {
  rbacLoading.value = true
  try {
    const { data } = await api.get('/rbac/permissions')
    if (data.code === 0) {
      permCatalog.value = data.data.items
    }
    await Promise.all(roleRows.map((row) => fetchRoleCodes(row.role)))
    rbacLoaded.value = true
  } catch (e) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '加载权限配置失败')
  } finally {
    rbacLoading.value = false
  }
}

/** 勾选变更：全量覆盖该角色权限码（PUT），成功后以服务端返回刷新该角色映射 */
const handlePermToggle = async (role: UserRole, code: string, checked: boolean) => {
  const next = checked
    ? [...roleCodes[role], code]
    : roleCodes[role].filter((c) => c !== code)
  savingRoles[role] = true
  try {
    const { data } = await api.put(`/rbac/roles/${role}/permissions`, { codes: next })
    if (data.code === 0) {
      roleCodes[role] = data.data.codes
      message.success(`「${roleName[role]}」权限点已更新`)
    } else {
      message.error(data.message || '权限点更新失败')
    }
  } catch (e) {
    // code=4000（防自我锁死等业务错误）/ 422（非法权限码）均展示后端 message
    const err = e as { response?: { data?: { code?: number; message?: string } } }
    message.error(err?.response?.data?.message || '权限点更新失败')
  } finally {
    savingRoles[role] = false
  }
}

const onPermChange = (
  event: { target: { checked: boolean } },
  role: UserRole,
  code: string,
) => {
  handlePermToggle(role, code, event.target.checked)
}

const handleTabChange = (key: string | number) => {
  if (String(key) === 'rbac' && !rbacLoaded.value && !rbacLoading.value) {
    fetchRbac()
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
.form-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.rbac-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text-secondary);
}
.rbac-col-head__tag {
  margin-bottom: 4px;
}
.rbac-col-head__name {
  font-weight: 500;
  line-height: 1.4;
}
.rbac-col-head__code {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}
.rbac-role-cell__code {
  margin-left: var(--space-2);
  font-size: 12px;
  color: var(--text-secondary);
}
/* disabled 复选框需要 span 包裹才能触发 Tooltip hover */
.rbac-check {
  display: inline-block;
}
</style>
