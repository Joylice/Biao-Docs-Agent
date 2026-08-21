import type { Ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

interface WebSocketOptions {
  /** 生成进度 0-1 */
  progress: Ref<number>
  /** 章节内容映射（流式累积写入） */
  chapters: Ref<Record<string, string>>
  /** 当前正在生成的章节号（WS 推送） */
  currentChapter: Ref<string>
  /** 是否生成中 */
  generating: Ref<boolean>
  /** 当前选中章节（生成中未选中时自动跟随） */
  selectedChapter: Ref<string>
  /** 连接/同步错误提示 */
  wsError: Ref<string>
  /** 生成完成（done 消息或轮询达标） */
  onDone: () => void
  /** 任务类事件：刷新分工映射 */
  onTaskEvent: () => void
  /** 4003 无权限 */
  onForbidden: () => void
}

/**
 * 方案生成 WebSocket：连接、消息路由、断线自动重连（最多 3 次）。
 * 与原内联实现逐条等价：4001 清 token 跳登录，4003 停止重连并回调。
 */
export function useGenerateWebSocket(projectId: string, opts: WebSocketOptions) {
  const router = useRouter()

  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let reconnectAttempts = 0

  const clearReconnect = () => {
    if (reconnectTimer !== null) { clearTimeout(reconnectTimer); reconnectTimer = null }
  }

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const token = localStorage.getItem('access_token') || ''
    const wsUrl = `${protocol}://${window.location.host}/ws/${projectId}?token=${encodeURIComponent(token)}`
    ws = new WebSocket(wsUrl)
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'progress') {
        opts.progress.value = data.progress
        opts.currentChapter.value = data.current_chapter || ''
        if (data.chapters) opts.chapters.value = data.chapters
        if (data.current_chapter && opts.generating.value && !opts.selectedChapter.value) {
          opts.selectedChapter.value = data.current_chapter
        }
        if (opts.wsError.value) opts.wsError.value = ''
      } else if (data.type === 'section_token') {
        const no = data.chapter_no
        if (no) {
          opts.chapters.value[no] = (opts.chapters.value[no] ?? '') + (data.delta ?? '')
          if (opts.generating.value && !opts.selectedChapter.value) opts.selectedChapter.value = no
        }
      } else if (data.type === 'section_done') {
        const no = data.chapter_no
        if (no && typeof data.content === 'string') opts.chapters.value[no] = data.content
      } else if (data.type === 'done') {
        opts.onDone()
      } else if (typeof data.type === 'string' && data.type.startsWith('task_')) {
        opts.onTaskEvent()
      }
    }
    ws.onclose = (event) => {
      if (event.code === 4001) {
        clearReconnect()
        localStorage.removeItem('access_token')
        message.warning('登录已过期，请重新登录')
        router.push({ name: 'Login' })
      } else if (event.code === 4003) {
        clearReconnect()
        opts.onForbidden()
      } else {
        reconnectAttempts += 1
        if (reconnectAttempts <= 3) {
          opts.wsError.value = '连接已断开，正在自动重连...'
          reconnectTimer = window.setTimeout(() => { opts.wsError.value = ''; connect() }, 3000)
        } else { opts.wsError.value = '连接已断开，请刷新页面重试' }
      }
    }
  }

  /** 开始生成前重置重连计数（对应原 reconnectAttempts = 0） */
  const resetReconnectAttempts = () => { reconnectAttempts = 0 }

  /** 卸载清理：停止重连定时器并关闭连接 */
  const dispose = () => {
    clearReconnect()
    ws?.close()
  }

  return { connect, resetReconnectAttempts, dispose }
}
