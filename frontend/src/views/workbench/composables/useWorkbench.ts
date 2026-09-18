import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { currentUserId } from '@/stores/currentUser'
import type { fetchWorkbenchSummary } from '@/api'

/** 任务分桶 key（与后端 /workbench/summary 的 tasks 字段一一对应） */
export type BucketKey = 'pending' | 'in_progress' | 'rejected' | 'submitted' | 'approved'

/** 待办条目（我的分桶与 owner 待审核共用结构） */
export interface TaskItem {
  assignment_id: string
  project_id: string
  project_name: string
  chapter_no: string
  title: string
  status: string
}

/** 参与项目进度（分工聚合 + 工作流阶段） */
export interface ProjectProgress {
  project_id: string
  project_name: string
  total: number
  approved: number
  percent: number
  phase: string
  status_dist: Partial<Record<BucketKey, number>>
}

export interface WorkbenchSummary {
  tasks: Record<BucketKey, TaskItem[]>
  my_projects: ProjectProgress[]
  /** 仅项目 owner 且名下项目存在 submitted 分工时非空 */
  owner_review_pending: TaskItem[]
}

export const BUCKET_ORDER: BucketKey[] = ['pending', 'in_progress', 'rejected', 'submitted', 'approved']

export const BUCKET_META: Record<BucketKey, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  rejected: { text: '被打回', color: 'error' },
  submitted: { text: '已提审', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
}

/** 项目工作流阶段 → 中文（未知阶段原样展示） */
export const PHASE_META: Record<string, string> = {
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

export interface WorkbenchDeps {
  api: { fetchWorkbenchSummary: typeof fetchWorkbenchSummary }
  routerPush: (to: { name: string; params?: Record<string, string> }) => void
}

/**
 * useWorkbench：工作台逻辑模型
 * - 聚合数据加载（单端点双视图；silent 静默刷新不闪骨架屏、不清已有数据）
 * - 5 桶待办统计 / 导航（分工页/项目列表/资料库）/ 项目名缩写
 * - 用户级 WebSocket 实时推送：心跳保活 + 指数退避重连（最多 5 次）+
 *   业务事件静默刷新；鉴权失败码（4001/4003）不重连；卸载关闭
 */
export function useWorkbench(deps: WorkbenchDeps) {
  const { api, routerPush } = deps

  const loading = ref(false)
  const loadError = ref('')
  const summary = ref<WorkbenchSummary>(emptySummary())

  /** 全部待办条目总数：为 0 时展示看板空态插画 */
  const totalTaskCount = computed(() =>
    BUCKET_ORDER.reduce((sum, bucket) => sum + summary.value.tasks[bucket].length, 0),
  )

  /** 拉取工作台聚合数据（单端点双视图；非 owner 的待审核清单为空；silent 时不触发骨架屏闪烁） */
  const fetchSummary = async (silent = false) => {
    if (!silent) {
      loading.value = true
    }
    loadError.value = ''
    try {
      const { data } = await api.fetchWorkbenchSummary()
      if (data.code === 0) {
        // 展开兜底：缺省分桶补空数组，避免模板取 undefined。
        // 注意 tasks 需按分桶逐个兜底（顶层展开会被后端 tasks 整体覆盖，分桶键缺失仍为 undefined）
        const raw = data.data ?? {}
        summary.value = {
          ...emptySummary(),
          ...raw,
          tasks: {
            ...emptySummary().tasks,
            ...(raw.tasks ?? {}),
          },
        }
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
    routerPush({ name: 'Division', params: { projectId } })
  }

  const goProjects = () => routerPush({ name: 'Projects' })
  const goMaterials = () => routerPush({ name: 'Materials' })

  /** 项目名缩写：截取前 6 字符（阶段8 任务凝练），tooltip 显全名由模板提供 */
  const projectAbbr = (name: string) => {
    if (!name) return ''
    return name.length > 6 ? `${name.slice(0, 6)}…` : name
  }

  /** 按项目分组的任务列表（每个桶内按 project_id 聚合） */
  interface ProjectTaskGroup {
    project_id: string
    project_name: string
    count: number
    tasks: TaskItem[]
  }

  const groupTasksByProject = (tasks: TaskItem[]): ProjectTaskGroup[] => {
    const map = new Map<string, ProjectTaskGroup>()
    for (const task of tasks) {
      const existing = map.get(task.project_id)
      if (existing) {
        existing.tasks.push(task)
        existing.count++
      } else {
        map.set(task.project_id, {
          project_id: task.project_id,
          project_name: task.project_name,
          count: 1,
          tasks: [task],
        })
      }
    }
    // 按任务数量倒序，任务多的项目排前面
    return Array.from(map.values()).sort((a, b) => b.count - a.count)
  }

  /** 各桶按项目分组后的结果 */
  const groupedTasks = computed(() => {
    const result: Record<BucketKey, ProjectTaskGroup[]> = {
      pending: [],
      in_progress: [],
      rejected: [],
      submitted: [],
      approved: [],
    }
    for (const bucket of BUCKET_ORDER) {
      result[bucket] = groupTasksByProject(summary.value.tasks[bucket])
    }
    return result
  })

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

  return {
    loading,
    loadError,
    summary,
    totalTaskCount,
    groupedTasks,
    fetchSummary,
    goDivision,
    goProjects,
    goMaterials,
    projectAbbr,
    connectUserWebSocket,
    closeUserWebSocket,
  }
}
