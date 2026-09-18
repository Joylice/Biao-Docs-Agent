/**
 * useWorkbench 工作台逻辑测试（mock API + stub WebSocket 全局）.
 * 覆盖：fetchSummary 成功/失败/silent 模式、缺省分桶兜底、统计、导航、
 *       WebSocket 连接/心跳/消息静默刷新/重连退避/鉴权失败不重连/关闭.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// stores/currentUser 依赖 api client（引 router → ui store pinia persist 访问 window），
// 单测环境 mock 掉切断链路
vi.mock('@/api/client', () => ({ default: {} }))

import { useWorkbench, BUCKET_META, PHASE_META } from '@/views/workbench/composables/useWorkbench'
import { currentUserId } from '@/stores/currentUser'
import type { WorkbenchSummary, TaskItem } from '@/views/workbench/composables/useWorkbench'

/* ---------------- helpers ---------------- */

const mkRes = (data: unknown, code = 0) => ({ data: { code, data } })

function mkTask(chapterNo: string, over: Partial<TaskItem> = {}): TaskItem {
  return {
    assignment_id: `a-${chapterNo}`,
    project_id: 'proj-1',
    project_name: '河北数转项目',
    chapter_no: chapterNo,
    title: `章节${chapterNo}`,
    status: 'pending',
    ...over,
  }
}

function mkSummary(over: Partial<WorkbenchSummary> = {}): WorkbenchSummary {
  return {
    tasks: {
      pending: [mkTask('1')],
      in_progress: [],
      rejected: [mkTask('2', { status: 'rejected' })],
      submitted: [],
      approved: [mkTask('3', { status: 'approved' })],
    },
    my_projects: [{ project_id: 'proj-1', project_name: '河北数转项目', total: 3, approved: 1, percent: 33, phase: 'review', status_dist: { approved: 1 } }],
    owner_review_pending: [],
    ...over,
  }
}

class MockWS {
  static OPEN = 1
  static instances: MockWS[] = []
  readyState = MockWS.OPEN
  url: string
  onopen: ((e?: unknown) => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn(() => { this.onclose?.({ code: 1000 }) })
  constructor(url: string) {
    this.url = url
    MockWS.instances.push(this)
  }
}

function setup(over: { fetchSummary?: ReturnType<typeof vi.fn> } = {}) {
  const fetchWorkbenchSummary = over.fetchSummary ?? vi.fn().mockResolvedValue(mkRes(mkSummary()))
  const routerPush = vi.fn()
  const wb = useWorkbench({
    api: { fetchWorkbenchSummary },
    routerPush,
  })
  return { wb, fetchWorkbenchSummary, routerPush }
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  MockWS.instances = []
  currentUserId.value = ''
  vi.stubGlobal('window', {
    location: { protocol: 'http:', host: 'localhost:5173' },
    setTimeout: vi.fn(() => 1),
    clearTimeout: vi.fn(),
    setInterval: vi.fn(() => 2),
    clearInterval: vi.fn(),
  })
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => 'test-token') })
  vi.stubGlobal('WebSocket', MockWS)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* ---------------- fetchSummary ---------------- */

describe('fetchSummary 数据加载', () => {
  it('成功：填充 summary，loading 复位', async () => {
    const { wb } = setup()
    await wb.fetchSummary()
    expect(wb.summary.value.tasks.pending).toHaveLength(1)
    expect(wb.summary.value.tasks.rejected).toHaveLength(1)
    expect(wb.summary.value.my_projects[0].project_name).toBe('河北数转项目')
    expect(wb.loadError.value).toBe('')
    expect(wb.loading.value).toBe(false)
  })

  it('缺省分桶兜底：后端缺字段补空数组，避免模板 undefined', async () => {
    const { wb, fetchWorkbenchSummary } = setup({
      fetchSummary: vi.fn().mockResolvedValue(mkRes({ tasks: { pending: [mkTask('1')] }, my_projects: [] })),
    })
    await wb.fetchSummary()
    expect(wb.summary.value.tasks.in_progress).toEqual([])
    expect(wb.summary.value.tasks.approved).toEqual([])
    expect(wb.summary.value.owner_review_pending).toEqual([])
    expect(fetchWorkbenchSummary).toHaveBeenCalledTimes(1)
  })

  it('业务错误：设置 loadError', async () => {
    const { wb } = setup({
      fetchSummary: vi.fn().mockResolvedValue(mkRes(null, 5001)),
    })
    await wb.fetchSummary()
    expect(wb.loadError.value).toBe('工作台数据加载失败')
  })

  it('silent 模式：不触发骨架屏、不设 loadError（保留旧视图）', async () => {
    const { wb, fetchWorkbenchSummary } = setup()
    await wb.fetchSummary()
    wb.loading.value = false
    fetchWorkbenchSummary.mockRejectedValue(new Error('net'))
    await wb.fetchSummary(true)
    expect(wb.loading.value).toBe(false) // silent 不动 loading
    expect(wb.loadError.value).toBe('') // silent 不清已有视图
    expect(wb.summary.value.tasks.pending).toHaveLength(1) // 旧数据保留
  })
})

/* ---------------- 统计与导航 ---------------- */

describe('统计与导航', () => {
  it('totalTaskCount：5 桶求和', async () => {
    const { wb } = setup()
    await wb.fetchSummary()
    expect(wb.totalTaskCount.value).toBe(3)
  })

  it('projectAbbr：超 6 字符截断加省略号，空串返回空', () => {
    const { wb } = setup()
    expect(wb.projectAbbr('河北省数转项目')).toBe('河北省数转项…')
    expect(wb.projectAbbr('河北数转项目')).toBe('河北数转项目') // 恰好 6 字符不截断
    expect(wb.projectAbbr('短名')).toBe('短名')
    expect(wb.projectAbbr('')).toBe('')
  })

  it('导航：Division 带 projectId / Projects / Materials', () => {
    const { wb, routerPush } = setup()
    wb.goDivision('p-1')
    expect(routerPush).toHaveBeenCalledWith({ name: 'Division', params: { projectId: 'p-1' } })
    wb.goProjects()
    expect(routerPush).toHaveBeenCalledWith({ name: 'Projects' })
    wb.goMaterials()
    expect(routerPush).toHaveBeenCalledWith({ name: 'Materials' })
  })

  it('常量导出：BUCKET_META/PHASE_META 完整', () => {
    expect(BUCKET_META.pending.text).toBe('待领取')
    expect(PHASE_META.review).toBe('审阅阶段')
    expect(PHASE_META.unknown_phase).toBeUndefined()
  })
})

/* ---------------- WebSocket ---------------- */

describe('用户级 WebSocket', () => {
  it('无 userId 时不建立连接（等待 /auth/me 后 watch 补连）', () => {
    const { wb } = setup()
    wb.connectUserWebSocket()
    expect(MockWS.instances).toHaveLength(0)
  })

  it('有 userId 时建立连接：URL 含 ws 协议与 token', () => {
    currentUserId.value = 'user-1'
    const { wb } = setup()
    wb.connectUserWebSocket()
    expect(MockWS.instances).toHaveLength(1)
    expect(MockWS.instances[0].url).toBe('ws://localhost:5173/ws/user/user-1?token=test-token')
  })

  it('onopen 后启动心跳（setInterval）', () => {
    currentUserId.value = 'user-1'
    const { wb } = setup()
    wb.connectUserWebSocket()
    const ws = MockWS.instances[0]
    ws.onopen?.()
    const setIntervalMock = (window as unknown as { setInterval: ReturnType<typeof vi.fn> }).setInterval
    expect(setIntervalMock).toHaveBeenCalled()
  })

  it('业务事件消息 → 静默刷新待办', async () => {
    currentUserId.value = 'user-1'
    const { wb, fetchWorkbenchSummary } = setup()
    wb.connectUserWebSocket()
    const ws = MockWS.instances[0]
    await wb.fetchSummary() // 初始 1 次
    ws.onmessage?.({ data: JSON.stringify({ type: 'task_assigned' }) })
    await vi.waitFor(() => {
      expect(fetchWorkbenchSummary).toHaveBeenCalledTimes(2)
    })
    // 非业务事件不触发
    ws.onmessage?.({ data: JSON.stringify({ type: 'pong' }) })
    expect(fetchWorkbenchSummary).toHaveBeenCalledTimes(2)
  })

  it('onclose 鉴权失败码（4001/4003）不重连', () => {
    currentUserId.value = 'user-1'
    const { wb } = setup()
    wb.connectUserWebSocket()
    MockWS.instances[0].onclose?.({ code: 4001 })
    const setTimeoutMock = (window as unknown as { setTimeout: ReturnType<typeof vi.fn> }).setTimeout
    expect(setTimeoutMock).not.toHaveBeenCalled()
  })

  it('onclose 普通断线 → 指数退避重连（setTimeout 1s）', () => {
    currentUserId.value = 'user-1'
    const { wb } = setup()
    wb.connectUserWebSocket()
    MockWS.instances[0].onclose?.({ code: 1006 })
    const setTimeoutMock = (window as unknown as { setTimeout: ReturnType<typeof vi.fn> }).setTimeout
    expect(setTimeoutMock).toHaveBeenCalledTimes(1)
  })

  it('closeUserWebSocket：关闭连接并停止重连', () => {
    currentUserId.value = 'user-1'
    const { wb } = setup()
    wb.connectUserWebSocket()
    const ws = MockWS.instances[0]
    wb.closeUserWebSocket()
    expect(ws.close).toHaveBeenCalled()
    // 停止后再触发 close 事件不会安排重连
    const setTimeoutMock = (window as unknown as { setTimeout: ReturnType<typeof vi.fn> }).setTimeout
    expect(setTimeoutMock).not.toHaveBeenCalled()
  })
})
