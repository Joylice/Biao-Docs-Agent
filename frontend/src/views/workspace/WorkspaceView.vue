<template>
  <div class="workspace">
    <!-- 顶部步骤条导航 -->
    <div class="workspace__header">
      <div class="workspace__header-inner">
        <div class="workspace__project-info">
          <a-button
            type="text"
            size="small"
            class="workspace__back-btn"
            @click="goBackToProjects"
          >
            <template #icon>
              <ArrowLeftOutlined />
            </template>
            返回
          </a-button>
          <div class="workspace__project-meta">
            <h2
              class="workspace__project-name"
              :title="projectName"
            >
              {{ projectName || '加载中…' }}
            </h2>
            <a-tag
              v-if="projectPhase"
              color="blue"
              class="workspace__phase-tag"
            >
              {{ phaseText }}
            </a-tag>
          </div>
        </div>

        <div class="workspace__header-actions">
          <a-button
            type="text"
            class="workspace__members-btn"
            @click="openMembersDrawer"
          >
            <template #icon>
              <TeamOutlined />
            </template>
            成员管理
          </a-button>
        </div>
      </div>

      <!-- 步骤条 -->
      <div class="workspace__steps-wrapper">
        <div class="workspace__steps-inner">
          <a-steps
            :current="currentStepIndex"
            size="small"
            class="workspace__steps"
            @change="handleStepChange"
          >
            <a-step
              v-for="(step, idx) in steps"
              :key="step.key"
              :title="step.label"
              :status="getStepStatus(idx)"
              :icon="step.icon"
            />
          </a-steps>
        </div>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="workspace__content">
      <div class="workspace__content-inner">
        <router-view />
      </div>
    </div>

    <!-- 成员管理抽屉 -->
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
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  FileSearchOutlined,
  BulbOutlined,
  EyeOutlined,
  EditOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'

interface ProjectDetail {
  id: string
  name: string
  owner_id: string
  status?: string
}

interface MemberItem {
  user_id: string
  email: string
  display_name: string
  is_owner: boolean
  joined_at: string
}

interface UserOption {
  id: string
  email: string
  display_name: string
}

const router = useRouter()
const route = useRoute()
const projectId = route.params.projectId as string

const projectName = ref('')
const projectOwnerId = ref('')
const projectPhase = ref('')

// 成员管理
const showMembersDrawer = ref(false)
const members = ref<MemberItem[]>([])
const membersLoading = ref(false)
const addUserId = ref<string | undefined>(undefined)
const addingMember = ref(false)
const userOptions = ref<UserOption[]>([])

const candidateOptions = computed(() => {
  const memberIds = new Set(members.value.map((m) => m.user_id))
  return userOptions.value
    .filter((u) => !memberIds.has(u.id))
    .map((u) => ({ value: u.id, label: `${u.display_name}（${u.email}）` }))
})

const isOwner = computed(() => projectOwnerId.value === currentUserId.value)

/* ---------------- 步骤条配置 ---------------- */
const steps = [
  { key: 'parse', label: '招标解析', route: 'Parse', icon: h(FileSearchOutlined) },
  { key: 'generate', label: '大纲生成', route: 'Generate', icon: h(BulbOutlined) },
  { key: 'review', label: '审阅', route: 'Review', icon: h(EyeOutlined) },
  { key: 'division', label: '方案生成', route: 'Division', icon: h(EditOutlined) },
]

const routeToStepIndex: Record<string, number> = {
  Parse: 0,
  Generate: 1,
  Review: 2,
  Division: 3,
}

const currentStepIndex = computed(() => {
  const idx = routeToStepIndex[String(route.name)]
  return idx !== undefined ? idx : 0
})

const phaseText = computed(() => {
  const map: Record<string, string> = {
    init: '待启动',
    parse: '解析中',
    generate: '生成中',
    generating: '生成中',
    review: '审阅中',
    done: '已完成',
  }
  return map[projectPhase.value] || projectPhase.value
})

const getStepStatus = (idx: number): 'wait' | 'process' | 'finish' | 'error' => {
  const current = currentStepIndex.value
  if (idx < current) return 'finish'
  if (idx === current) return 'process'
  return 'wait'
}

const handleStepChange = (idx: number) => {
  const step = steps[idx]
  if (step) {
    router.push({ name: step.route, params: { projectId } })
  }
}

/* ---------------- 数据加载 ---------------- */
const fetchProject = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) {
      const project = data.data as ProjectDetail
      projectName.value = project.name
      projectOwnerId.value = project.owner_id
      projectPhase.value = project.status || ''
    }
  } catch {
    projectName.value = '加载失败'
  }
}

const fetchMembers = async () => {
  membersLoading.value = true
  try {
    const { data } = await api.get(`/projects/${projectId}/members`)
    if (data.code === 0) {
      members.value = data.data.items
    }
  } catch {
    message.error('成员列表加载失败')
  } finally {
    membersLoading.value = false
  }
}

const loadUserOptions = async () => {
  try {
    const { data } = await api.get('/users/options')
    if (data.code === 0) {
      userOptions.value = data.data.items
    }
  } catch {
    // 静默失败
  }
}

const openMembersDrawer = () => {
  showMembersDrawer.value = true
  fetchMembers()
  loadUserOptions()
}

const formatTime = (time?: string): string => {
  if (!time) return '—'
  const d = new Date(time)
  if (Number.isNaN(d.getTime())) return time
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

const handleRemoveMember = async (userId: string) => {
  try {
    const { data } = await api.delete(`/projects/${projectId}/members/${userId}`)
    if (data.code === 0) {
      message.success('成员移除成功')
      fetchMembers()
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
    }
  } catch (err) {
    message.error(getErrorMessage(err, '成员添加失败'))
  } finally {
    addingMember.value = false
  }
}

const goBackToProjects = () => {
  router.push({ name: 'Projects' })
}

onMounted(() => {
  fetchProject()
  fetchCurrentUserRole()
})

// 路由变化时刷新项目状态（轻量）
watch(
  () => route.name,
  () => {
    fetchProject()
  },
)
</script>

<style scoped>
.workspace {
  min-height: 100vh;
  background: var(--bg-app);
  display: flex;
  flex-direction: column;
}

/* 顶部区域 */
.workspace__header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
  backdrop-filter: blur(12px);
}

.workspace__header-inner {
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.workspace__project-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.workspace__back-btn {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.workspace__project-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.workspace__project-name {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
}

.workspace__phase-tag {
  flex-shrink: 0;
}

.workspace__header-actions {
  flex-shrink: 0;
}

.workspace__members-btn {
  color: var(--text-secondary);
}

/* 步骤条 */
.workspace__steps-wrapper {
  border-top: 1px solid var(--border-color-light);
  background: var(--bg-surface-hover);
}

.workspace__steps-inner {
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 12px 24px;
}

.workspace__steps {
  cursor: pointer;
}

.workspace__steps :deep(.ant-steps-item) {
  cursor: pointer;
}

.workspace__steps :deep(.ant-steps-item-title) {
  font-weight: 500;
}

.workspace__steps :deep(.ant-steps-item-process .ant-steps-item-title) {
  color: var(--color-primary) !important;
  font-weight: 600;
}

/* 内容区 */
.workspace__content {
  flex: 1;
  min-width: 0;
}

.workspace__content-inner {
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: 24px;
}

/* 成员抽屉 */
.member-name {
  font-weight: 500;
}

.member-tag {
  margin-left: 8px;
}

.member-joined {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.member-add {
  display: flex;
  gap: 8px;
}
</style>
