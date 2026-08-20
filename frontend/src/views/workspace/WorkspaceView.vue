<template>
  <a-layout class="workspace">
    <a-layout-sider
      theme="light"
      :width="200"
      :collapsed="siderCollapsed"
      :collapsed-width="64"
      :trigger="null"
      collapsible
      class="workspace__sider"
    >
      <div class="workspace__project">
        <span class="workspace__project-icon">
          <FolderOutlined />
        </span>
        <div
          v-if="!siderCollapsed"
          class="workspace__project-info"
        >
          <span class="workspace__project-label">当前项目</span>
          <span
            class="workspace__project-name"
            :title="projectName"
          >
            {{ projectName || '加载中…' }}
          </span>
        </div>
        <a-button
          v-if="!siderCollapsed"
          class="workspace__collapse-btn"
          type="text"
          size="small"
          @click="siderCollapsed = true"
        >
          <template #icon>
            <MenuFoldOutlined />
          </template>
        </a-button>
      </div>
      <a-button
        v-if="siderCollapsed"
        class="workspace__expand-btn"
        type="text"
        size="small"
        @click="siderCollapsed = false"
      >
        <template #icon>
          <MenuUnfoldOutlined />
        </template>
      </a-button>
      <a-menu
        mode="inline"
        :selected-keys="selectedKeys"
        :items="menuItems"
        :inline-collapsed="siderCollapsed"
        @click="handleMenuClick"
      />
      <div class="workspace__footer">
        <a-button
          type="text"
          block
          @click="goBackToProjects"
        >
          <template #icon>
            <ArrowLeftOutlined />
          </template>
          <span v-if="!siderCollapsed">返回项目列表</span>
        </a-button>
      </div>
    </a-layout-sider>
    <a-layout-content class="workspace-content">
      <router-view />
    </a-layout-content>

    <!-- 成员管理抽屉：列表 + 移除（仅 owner）+ 添加协作者 -->
    <!-- 注意：必须位于 a-layout 单根节点内 —— App.vue 的 <Transition mode="out-in"> -->
    <!-- 无法对 fragment（多根）组件做过渡，否则路由跳转时静默白屏 -->
    <a-drawer
      v-model:open="showMembersDrawer"
      title="成员管理"
      :width="420"
    >
      <a-spin :spinning="membersLoading">
        <a-list
          :data-source="members"
          :locale="{ emptyText: '暂无成员' }"
        >
          <template #renderItem="{ item }">
            <a-list-item>
              <a-list-item-meta>
                <template #title>
                  <span class="member-name">{{ item.display_name }}</span>
                  <a-tag
                    v-if="item.is_owner"
                    color="gold"
                    class="member-tag"
                  >
                    所有者
                  </a-tag>
                  <a-tag
                    v-if="item.user_id === currentUserId"
                    color="blue"
                    class="member-tag"
                  >
                    我
                  </a-tag>
                </template>
                <template #description>
                  <div>{{ item.email }}</div>
                  <div class="member-joined">
                    {{ formatTime(item.joined_at) }} 加入
                  </div>
                </template>
              </a-list-item-meta>
              <a-popconfirm
                v-if="isOwner && !item.is_owner"
                title="确定移除该成员？"
                ok-text="移除"
                cancel-text="取消"
                @confirm="handleRemoveMember(item.user_id)"
              >
                <a-button
                  type="text"
                  danger
                  size="small"
                >
                  移除
                </a-button>
              </a-popconfirm>
            </a-list-item>
          </template>
        </a-list>
      </a-spin>
      <template #footer>
        <div
          v-if="isOwner"
          class="member-add"
        >
          <a-select
            v-model:value="addUserId"
            :options="candidateOptions"
            placeholder="选择协作者（姓名/邮箱）"
            show-search
            allow-clear
            option-filter-prop="label"
            style="flex: 1"
          />
          <a-button
            type="primary"
            :loading="addingMember"
            @click="handleAddMember"
          >
            添加
          </a-button>
        </div>
      </template>
    </a-drawer>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import type { MenuProps } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  FolderOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import api from '@/api/client'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'

interface ProjectDetail {
  id: string
  name: string
  owner_id: string
}

interface MemberItem {
  user_id: string
  email: string
  display_name: string
  is_owner: boolean
  joined_at: string
}

const router = useRouter()
const route = useRoute()
const projectId = route.params.projectId as string

const projectName = ref('')
const projectOwnerId = ref('')

// 成员管理抽屉状态
const showMembersDrawer = ref(false)
const members = ref<MemberItem[]>([])
const membersLoading = ref(false)
const addUserId = ref<string | undefined>(undefined)
const addingMember = ref(false)

// 阶段7：协作者下拉数据源（GET /users/options，排除已有成员）
interface UserOption {
  id: string
  email: string
  display_name: string
}
const userOptions = ref<UserOption[]>([])

const candidateOptions = computed(() => {
  const memberIds = new Set(members.value.map((m) => m.user_id))
  return userOptions.value
    .filter((u) => !memberIds.has(u.id))
    .map((u) => ({ value: u.id, label: `${u.display_name}（${u.email}）` }))
})

const loadUserOptions = async () => {
  try {
    const { data } = await api.get('/users/options')
    if (data.code === 0) {
      userOptions.value = data.data.items
    }
  } catch {
    // 下拉数据源加载失败不阻塞成员列表展示
  }
}

// 侧栏折叠态持久化（localStorage）
const SIDER_KEY = 'bid.workspace.sider.collapsed'
const siderCollapsed = ref(localStorage.getItem(SIDER_KEY) === '1')
watch(siderCollapsed, (v) => {
  localStorage.setItem(SIDER_KEY, v ? '1' : '0')
})

// 菜单 key → 路由 name 映射（菜单 key 与路由 name 不一致，需显式映射）
const menuRoutes: Record<string, string> = {
  parse: 'Parse',
  generate: 'Generate',
  review: 'Review',
  division: 'Division',
}

// 路由 name → 菜单 key（选中态反查）
const routeMenuKeys: Record<string, string> = {
  Parse: 'parse',
  Generate: 'generate',
  Review: 'review',
  Division: 'division',
}

// 按投标流程步骤先后排列：招标解析 → 方案大纲生成 → 审阅 → 方案生成
const menuItems: MenuProps['items'] = [
  {
    key: 'parse',
    icon: () => h('span', { class: 'workspace__step' }, '1'),
    label: '招标解析',
  },
  {
    key: 'generate',
    icon: () => h('span', { class: 'workspace__step' }, '2'),
    label: '方案大纲生成',
  },
  {
    key: 'review',
    icon: () => h('span', { class: 'workspace__step' }, '3'),
    label: '审阅',
  },
  {
    key: 'division',
    icon: () => h('span', { class: 'workspace__step' }, '4'),
    label: '方案生成',
  },
  {
    key: 'members',
    icon: () => h(TeamOutlined),
    label: '成员管理',
  },
]

const selectedKeys = computed(() => {
  const key = routeMenuKeys[String(route.name)]
  return key ? [key] : []
})

const fetchProject = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) {
      const project = data.data as ProjectDetail
      projectName.value = project.name
      projectOwnerId.value = project.owner_id
    } else {
      projectName.value = '加载失败'
    }
  } catch {
    // 项目不存在或无权访问：详情接口失败时明确展示失败态，避免静默
    projectName.value = '加载失败'
  }
}

// 当前用户是否为项目所有者（决定移除/添加入口可见性）
const isOwner = computed(() => projectOwnerId.value === currentUserId.value)

const fetchMembers = async () => {
  membersLoading.value = true
  try {
    const { data } = await api.get(`/projects/${projectId}/members`)
    if (data.code === 0) {
      members.value = data.data.items
    } else {
      message.error(data.message || '成员列表加载失败')
    }
  } catch {
    message.error('成员列表加载失败')
  } finally {
    membersLoading.value = false
  }
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

const formatTime = (time?: string): string => {
  if (!time) return '—'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return time
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const handleRemoveMember = async (userId: string) => {
  try {
    const { data } = await api.delete(`/projects/${projectId}/members/${userId}`)
    if (data.code === 0) {
      message.success('成员移除成功')
      fetchMembers()
    } else {
      message.error(data.message || '成员移除失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '成员移除失败'))
  }
}

const handleAddMember = async () => {
  const selected = userOptions.value.find((u) => u.id === addUserId.value)
  if (!selected) {
    message.warning('请选择协作者')
    return
  }
  addingMember.value = true
  try {
    const { data } = await api.post(`/projects/${projectId}/members`, {
      email: selected.email,
    })
    if (data.code === 0) {
      message.success('成员添加成功')
      addUserId.value = undefined
      fetchMembers()
    } else {
      message.error(data.message || '成员添加失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '成员添加失败'))
  } finally {
    addingMember.value = false
  }
}

const handleMenuClick = ({ key }: { key: string }) => {
  if (key === 'members') {
    showMembersDrawer.value = true
    fetchMembers()
    loadUserOptions()
    return
  }
  const name = menuRoutes[key]
  if (!name) return
  router.push({ name, params: { projectId } })
}

const goBackToProjects = () => {
  router.push({ name: 'Projects' })
}

onMounted(() => {
  fetchProject()
  // 工作台不使用 AppLayout，自行同步当前用户身份（owner 判定依赖）
  fetchCurrentUserRole()
})
</script>

<style scoped>
.workspace {
  min-height: 100vh;
}

.workspace__sider {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  border-right: 1px solid var(--border-color);
}

.workspace__project {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border-bottom: 1px solid var(--border-color);
}

.workspace__collapse-btn {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary, #999);
}

.workspace__expand-btn {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary, #999);
}

.workspace__project-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--color-primary);
  color: #fff;
  font-size: 16px;
  flex-shrink: 0;
}

.workspace__project-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.workspace__project-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.workspace__project-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workspace__footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 12px 8px;
  border-top: 1px solid var(--border-color);
}

.workspace-content {
  padding: 24px;
  background: var(--app-bg);
  min-width: 0;
  display: flex;
  justify-content: center;
}

.workspace-content > * {
  width: 100%;
  max-width: 1100px;
}

.workspace__step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
}

/* 成员管理抽屉 */
.member-name {
  font-weight: 500;
}

.member-tag {
  margin-left: 8px;
}

.member-joined {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary, #666);
}

.member-add {
  display: flex;
  gap: 8px;
}
</style>
