<template>
  <div class="workbench">
    <PageContainer
      title="工作台"
      subtitle="我的章节待办与项目进度一览"
    >
      <LoadingSkeleton
        v-if="loading"
        :rows="6"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchSummary"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <template v-else>
        <!-- 快捷操作区 -->
        <div class="workbench__quick-actions">
          <a-button
            type="primary"
            @click="goProjects"
          >
            <template #icon>
              <PlusOutlined />
            </template>
            新建项目
          </a-button>
          <a-button @click="goProjects">
            <template #icon>
              <FolderOpenOutlined />
            </template>
            全部项目
          </a-button>
          <a-button @click="goMaterials">
            <template #icon>
              <DatabaseOutlined />
            </template>
            资料库
          </a-button>
        </div>

        <!-- 我的待办：5 桶（待领取/编制中/被打回/已提审/已通过），条目直达项目分工页 -->
        <div class="workbench__section-title">
          我的待办
        </div>
        <div class="workbench__buckets">
          <a-card
            v-for="bucket in BUCKET_ORDER"
            :key="bucket"
            class="workbench__bucket"
          >
            <template #title>
              <span class="workbench__bucket-name">{{ BUCKET_META[bucket].text }}</span>
              <a-tag
                class="workbench__bucket-count"
                :color="BUCKET_META[bucket].color"
              >
                {{ summary.tasks[bucket].length }}
              </a-tag>
            </template>
            <div
              v-if="summary.tasks[bucket].length === 0"
              class="workbench__bucket-empty"
            >
              暂无任务
            </div>
            <a-list
              v-else
              size="small"
              class="workbench__task-list"
              :data-source="summary.tasks[bucket]"
            >
              <template #renderItem="{ item }">
                <a-list-item
                  class="workbench__task"
                  @click="goDivision(item.project_id)"
                >
                  <a-tooltip
                    :title="`${item.project_name} · ${item.chapter_no} ${item.title}`"
                  >
                    <span class="workbench__task-text">
                      {{ item.chapter_no }} {{ item.title }} ·
                      <span class="workbench__task-proj">{{ projectAbbr(item.project_name) }}</span>
                    </span>
                  </a-tooltip>
                </a-list-item>
              </template>
            </a-list>
          </a-card>
        </div>

        <!-- 负责人视图：名下/参与项目进度看板 + 待审核清单（两者任一非空即显示） -->
        <template v-if="summary.my_projects.length > 0 || summary.owner_review_pending.length > 0">
          <div class="workbench__section-title">
            项目进度
          </div>
          <a-row :gutter="16">
            <a-col :span="summary.owner_review_pending.length > 0 ? 14 : 24">
              <a-card
                title="项目分工进度"
                class="workbench__board-card"
              >
                <div
                  v-for="proj in summary.my_projects"
                  :key="proj.project_id"
                  class="workbench__project"
                >
                  <div class="workbench__project-head">
                    <a
                      class="workbench__project-name"
                      :title="proj.project_name"
                      @click="goDivision(proj.project_id)"
                    >
                      {{ proj.project_name }}
                    </a>
                    <a-tag
                      v-if="proj.phase"
                      color="blue"
                    >
                      {{ PHASE_META[proj.phase] || proj.phase }}
                    </a-tag>
                    <span class="workbench__project-count">已通过 {{ proj.approved }}/{{ proj.total }}</span>
                  </div>
                  <a-progress
                    :percent="proj.percent"
                    size="small"
                  />
                  <a-space
                    size="4"
                    wrap
                    class="workbench__project-dist"
                  >
                    <template
                      v-for="bucket in BUCKET_ORDER"
                      :key="bucket"
                    >
                      <a-tag
                        v-if="proj.status_dist[bucket]"
                        :color="BUCKET_META[bucket].color"
                      >
                        {{ BUCKET_META[bucket].text }} {{ proj.status_dist[bucket] }}
                      </a-tag>
                    </template>
                  </a-space>
                </div>
              </a-card>
            </a-col>
            <a-col
              v-if="summary.owner_review_pending.length > 0"
              :span="10"
            >
              <a-card
                class="workbench__board-card"
              >
                <template #title>
                  待我审核
                  <a-tag
                    color="warning"
                    class="workbench__bucket-count"
                  >
                    {{ summary.owner_review_pending.length }}
                  </a-tag>
                </template>
                <a-list
                  size="small"
                  :data-source="summary.owner_review_pending"
                >
                  <template #renderItem="{ item }">
                    <a-list-item
                      class="workbench__task"
                      @click="goDivision(item.project_id)"
                    >
                      <a-tooltip
                        :title="`${item.project_name} · ${item.chapter_no} ${item.title}`"
                      >
                        <span class="workbench__task-text">
                          {{ item.chapter_no }} {{ item.title }} ·
                          <span class="workbench__task-proj">{{ projectAbbr(item.project_name) }}</span>
                        </span>
                      </a-tooltip>
                    </a-list-item>
                  </template>
                </a-list>
              </a-card>
            </a-col>
          </a-row>
        </template>
      </template>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { PlusOutlined, FolderOpenOutlined, DatabaseOutlined } from '@ant-design/icons-vue'
import api from '@/api/client'
import { currentUserId } from '@/stores/currentUser'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

/** 任务分桶 key（与后端 /workbench/summary 的 tasks 字段一一对应） */
type BucketKey = 'pending' | 'in_progress' | 'rejected' | 'submitted' | 'approved'

/** 待办条目（我的分桶与 owner 待审核共用结构） */
interface TaskItem {
  assignment_id: string
  project_id: string
  project_name: string
  chapter_no: string
  title: string
  status: string
}

/** 参与项目进度（分工聚合 + 工作流阶段） */
interface ProjectProgress {
  project_id: string
  project_name: string
  total: number
  approved: number
  percent: number
  phase: string
  status_dist: Partial<Record<BucketKey, number>>
}

interface WorkbenchSummary {
  tasks: Record<BucketKey, TaskItem[]>
  my_projects: ProjectProgress[]
  /** 仅项目 owner 且名下项目存在 submitted 分工时非空 */
  owner_review_pending: TaskItem[]
}

const BUCKET_ORDER: BucketKey[] = ['pending', 'in_progress', 'rejected', 'submitted', 'approved']

const BUCKET_META: Record<BucketKey, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

/** 项目工作流阶段 → 中文（未知阶段原样展示） */
const PHASE_META: Record<string, string> = {
  init: '待启动',
  generate: '生成中',
  generating: '生成中',
  review: '审阅阶段',
  done: '已完成',
}

const emptySummary = (): WorkbenchSummary => ({
  tasks: { pending: [], in_progress: [], rejected: [], submitted: [], approved: [] },
  my_projects: [],
  owner_review_pending: [],
})

const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const summary = ref<WorkbenchSummary>(emptySummary())

/** 拉取工作台聚合数据（单端点双视图；非 owner 的待审核清单为空；silent 时不触发骨架屏闪烁） */
const fetchSummary = async (silent = false) => {
  if (!silent) {
    loading.value = true
  }
  loadError.value = ''
  try {
    const { data } = await api.get('/workbench/summary')
    if (data.code === 0) {
      // 展开兜底：缺省分桶补空数组，避免模板取 undefined
      summary.value = { ...emptySummary(), ...(data.data ?? {}) }
    } else {
      // 静默刷新失败不打断已有视图（保留旧数据，手动刷新可重试）
      if (!silent) {
        loadError.value = data.message || '工作台数据加载失败'
      }
    }
  } catch {
    if (!silent) {
      loadError.value = '工作台数据加载失败'
    }
  } finally {
    if (!silent) {
      loading.value = false
    }
  }
}

/** 条目点击 → 对应项目的方案生成页 */
const goDivision = (projectId: string) => {
  router.push({ name: 'Division', params: { projectId } })
}

const goProjects = () => router.push({ name: 'Projects' })
const goMaterials = () => router.push({ name: 'Materials' })

/** 项目名缩写：截取前 6 字符（阶段8 任务凝练），tooltip 显全名由模板提供 */
const projectAbbr = (name: string) => {
  if (!name) return ''
  return name.length > 6 ? `${name.slice(0, 6)}…` : name
}

/* ---------------- 用户级 WebSocket：待办实时推送（阶段 C；静默降级，不影响页面渲染） ---------------- */
const WS_EVENTS = ['task_assigned', 'task_submitted', 'task_reviewed', 'workbench_refresh']
const WS_MAX_RECONNECTS = 5
const WS_HEARTBEAT_MS = 30000

let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let heartbeatTimer: number | null = null
let reconnectAttempts = 0
let wsStopped = false

const stopHeartbeat = () => {
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

/** 心跳保活：定期发 ping（后端回 pong），防止空闲连接被中间层断开 */
const startHeartbeat = () => {
  stopHeartbeat()
  heartbeatTimer = window.setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }))
    }
  }, WS_HEARTBEAT_MS)
}

const connectUserWebSocket = () => {
  if (wsStopped || ws) return
  const userId = currentUserId.value
  if (!userId) return // 未拿到用户 ID：由 watch 在 /auth/me 就绪后补连，手动刷新仍可用
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('access_token') || ''
  const wsUrl = `${protocol}://${window.location.host}/ws/user/${userId}?token=${encodeURIComponent(token)}`
  try {
    ws = new WebSocket(wsUrl)
  } catch {
    return // 连接创建失败：静默降级
  }
  ws.onopen = () => {
    reconnectAttempts = 0
    startHeartbeat()
  }
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (WS_EVENTS.includes(data.type)) {
        // 任意业务事件 → 静默刷新待办（不弹提示、不闪骨架屏）
        fetchSummary(true)
      }
    } catch {
      // 非 JSON 消息（如 pong 之外的文本）忽略
    }
  }
  ws.onclose = (event) => {
    stopHeartbeat()
    ws = null // 连接已关闭：清空引用，允许重连/补连重新建立
    if (wsStopped) return
    // 鉴权失败（4001 token 无效 / 4003 订阅他人频道）：重连无意义，静默降级
    if (event.code === 4001 || event.code === 4003) return
    // 断线指数退避重连：1s 起步倍增，最多 5 次
    reconnectAttempts += 1
    if (reconnectAttempts <= WS_MAX_RECONNECTS) {
      const delay = 1000 * 2 ** (reconnectAttempts - 1)
      reconnectTimer = window.setTimeout(connectUserWebSocket, delay)
    }
  }
  ws.onerror = () => {
    // 静默：错误统一由 onclose 走重连/降级逻辑
  }
}

// currentUserId 由 AppLayout 拉取 /auth/me 异步写入：晚于本页挂载时经 watch 补连（防静默丢失实时推送）
watch(currentUserId, (userId) => {
  if (userId && !wsStopped && !ws) {
    connectUserWebSocket()
  }
})

/** 关闭连接并停止一切重连（页面卸载） */
const closeUserWebSocket = () => {
  wsStopped = true
  stopHeartbeat()
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  reconnectAttempts = WS_MAX_RECONNECTS
  ws?.close()
  ws = null
}

onMounted(() => {
  fetchSummary()
  connectUserWebSocket()
})

onUnmounted(closeUserWebSocket)
</script>

<style scoped>
.workbench {
  max-width: 1200px;
}

.workbench__quick-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.workbench__section-title {
  margin: 4px 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.workbench__buckets {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}

.workbench__bucket {
  flex: 1 1 200px;
  min-width: 200px;
  background: var(--card-bg);
}

.workbench__bucket-name {
  font-size: 13px;
  font-weight: 600;
}

.workbench__bucket-count {
  margin-left: 8px;
}

.workbench__bucket-empty {
  padding: 12px 0;
  font-size: 12px;
  color: var(--text-secondary, #999);
  text-align: center;
}

.workbench__task-list {
  max-height: 264px;
  overflow-y: auto;
}

.workbench__task {
  cursor: pointer;
  transition: background 0.15s;
}

.workbench__task:hover {
  background: var(--bg-hover);
}

.workbench__task-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.workbench__task-proj {
  color: var(--text-secondary, #999);
}

.workbench__board-card {
  background: var(--card-bg);
  height: 100%;
}

.workbench__project {
  padding: 10px 0;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}

.workbench__project:last-child {
  border-bottom: none;
}

.workbench__project-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  min-width: 0;
}

.workbench__project-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench__project-count {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.workbench__project-dist {
  margin-top: 6px;
}
</style>
