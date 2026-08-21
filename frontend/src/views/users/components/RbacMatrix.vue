<template>
  <div>
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
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchPermissionCatalog,
  fetchRolePermissionCodes,
  updateRolePermissionCodes,
} from '@/api'
import type { UserRole } from '@/stores/currentUser'
import { roleName, type PermItem } from '../constants'

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
  const { data } = await fetchRolePermissionCodes(role)
  if (data.code === 0) {
    roleCodes[role] = data.data.codes
  }
}

const fetchRbac = async () => {
  rbacLoading.value = true
  try {
    const { data } = await fetchPermissionCatalog()
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
    const { data } = await updateRolePermissionCodes(role, next)
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

/** 切换到角色权限 tab 时按需加载（父组件 tab change 调用） */
const loadIfNeeded = () => {
  if (!rbacLoaded.value && !rbacLoading.value) fetchRbac()
}

defineExpose({ loadIfNeeded })
</script>

<style scoped>
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
