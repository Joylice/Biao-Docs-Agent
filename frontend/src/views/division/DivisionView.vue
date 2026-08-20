<template>
  <div class="division-view">
    <PageContainer
      title="方案生成与分工"
      subtitle="拖拽卡片切换状态，点击卡片编辑章节内容"
    >
      <!-- 工具栏 -->
      <div class="division-view__toolbar">
        <a-space wrap>
          <a-select
            v-model:value="filterAssignee"
            placeholder="全部负责人"
            allow-clear
            style="width: 180px"
            :options="assigneeFilterOptions"
          />
          <a-tag color="blue">共 {{ filteredItems.length }} 个章节</a-tag>
          <a-tag v-if="myTaskCount > 0" color="processing">我的任务 {{ myTaskCount }}</a-tag>
        </a-space>
        <a-space>
          <a-button @click="fetchAll" :loading="loading">
            <template #icon><ReloadOutlined /></template>
            刷新
          </a-button>
          <a-button type="primary" @click="goToGenerate">
            <template #icon><ArrowLeftOutlined /></template>
            返回大纲
          </a-button>
        </a-space>
      </div>

      <!-- 加载/错误状态 -->
      <LoadingSkeleton v-if="loading" :rows="6" />
      <ErrorState v-else-if="loadError" :description="loadError">
        <template #action>
          <a-button type="primary" @click="fetchAll">重试</a-button>
        </template>
      </ErrorState>

      <!-- 5列泳道看板 -->
      <template v-else>
        <DivisionKanban
          :items="filteredItems"
          @select="handleSelectTask"
          @move="handleMoveTask"
        />
      </template>
    </PageContainer>

    <!-- 章节编辑抽屉 -->
    <ChapterEditorDrawer
      :visible="editorOpen"
      :task="editingTask"
      :project-id="projectId"
      :is-owner="isOwner"
      @close="editorOpen = false"
      @updated="handleTaskUpdated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import DivisionKanban from './components/DivisionKanban.vue'
import ChapterEditorDrawer from './components/ChapterEditorDrawer.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'
import type { AssignmentItem, TaskStatus, AssignmentNode } from '@/types'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const { isProjectOwner } = usePermission()

// 状态
const loading = ref(false)
const loadError = ref('')
const items = ref<AssignmentItem[]>([])
const projectOwnerId = ref('')

// 筛选
const filterAssignee = ref<string | undefined>(undefined)

// 编辑抽屉
const editorOpen = ref(false)
const editingTask = ref<AssignmentItem | null>(null)

const isOwner = computed(() => isProjectOwner(projectOwnerId.value))

const assigneeFilterOptions = computed(() => {
  const map = new Map<string, string>()
  items.value.forEach((item) => {
    if (item.assignee_id && item.assignee_name) {
      map.set(item.assignee_id, item.assignee_name)
    }
  })
  return Array.from(map.entries()).map(([value, label]) => ({ value, label }))
})

const filteredItems = computed(() => {
  if (!filterAssignee.value) return items.value
  return items.value.filter((item) => item.assignee_id === filterAssignee.value)
})

const myTaskCount = computed(() =>
  items.value.filter(
    (item) => item.assignee_id === currentUserId.value && item.status !== 'approved',
  ).length,
)

/* ---------------- 数据加载 ---------------- */
const fetchAssignments = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}/chapter-assignments`)
    if (data.code === 0) {
      // 拍平树形结构
      const flat: AssignmentItem[] = []
      const flatten = (nodes: AssignmentNode[]) => {
        nodes.forEach((node) => {
          if (node.id) {
            flat.push(node as unknown as AssignmentItem)
          }
          if (node.children?.length) flatten(node.children)
        })
      }
      flatten(data.data?.items || [])
      items.value = flat
    }
  } catch {
    loadError.value = '分工数据加载失败'
  }
}

const fetchProjectOwner = async () => {
  try {
    const { data } = await api.get(`/projects/${projectId}`)
    if (data.code === 0) {
      projectOwnerId.value = data.data?.owner_id || ''
    }
  } catch {
    // 静默失败
  }
}

const fetchAll = async () => {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([fetchAssignments(), fetchProjectOwner()])
  } finally {
    loading.value = false
  }
}

/* ---------------- 看板交互 ---------------- */
const handleSelectTask = (item: AssignmentItem) => {
  editingTask.value = item
  editorOpen.value = true
}

const handleMoveTask = async (item: AssignmentItem, targetStatus: TaskStatus) => {
  // 拖拽状态变更：根据目标状态执行对应操作
  try {
    if (targetStatus === 'in_progress' && item.status === 'pending') {
      // 领取
      await api.post(`/projects/${projectId}/assignments/${item.id}/accept`)
      message.success(`已领取：${item.title}`)
    } else if (targetStatus === 'submitted' && item.status === 'in_progress') {
      // 提交
      await api.post(`/projects/${projectId}/assignments/${item.id}/submit`)
      message.success(`已提交：${item.title}`)
    } else if (targetStatus === 'approved' && item.status === 'submitted') {
      // 审核通过
      await api.post(`/projects/${projectId}/assignments/${item.id}/approve`)
      message.success(`已通过：${item.title}`)
    } else if (targetStatus === 'rejected' && item.status === 'submitted') {
      // 打回（需要原因，这里用默认原因）
      await api.post(`/projects/${projectId}/assignments/${item.id}/reject`, {
        comment: '看板拖拽打回，请在编辑抽屉中查看详情',
      })
      message.success(`已打回：${item.title}`)
    } else {
      message.warning('该状态转换不支持，请通过卡片按钮操作')
      return
    }
    await fetchAssignments()
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '状态变更失败')
    await fetchAssignments() // 刷新回原状态
  }
}

const handleTaskUpdated = () => {
  fetchAssignments()
}

const goToGenerate = () => {
  router.push({ name: 'Generate', params: { projectId } })
}

onMounted(() => {
  fetchAll()
  fetchCurrentUserRole()
})
</script>

<style scoped>
.division-view {
  width: 100%;
}

.division-view__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}
</style>
