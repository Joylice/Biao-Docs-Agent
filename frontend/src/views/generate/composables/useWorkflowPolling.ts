/**
 * 工作流轮询通用封装：大纲生成轮询（2s/120 次）与方案生成状态轮询（3s/100 次）共用。
 * 行为与拆分前 GenerateView 内 startOutlinePolling/startGenPolling 逐条等价。
 */
import { ref } from 'vue'

export function useWorkflowPolling(options: {
  intervalMs: number
  maxCount: number
  /** 每次轮询执行的回调；返回 false 表示终止轮询 */
  onTick: () => Promise<boolean> | boolean
  /** 超过 maxCount 时的收尾（超时提示等） */
  onTimeout?: () => void
}) {
  const polling = ref(false)
  let timer: number | null = null
  let count = 0

  const stop = () => {
    if (timer !== null) { clearInterval(timer); timer = null }
    polling.value = false
  }

  const start = () => {
    if (timer !== null) return
    polling.value = true
    timer = window.setInterval(async () => {
      count += 1
      if (count > options.maxCount) {
        stop()
        options.onTimeout?.()
        return
      }
      const keepGoing = await options.onTick()
      if (keepGoing === false) stop()
    }, options.intervalMs)
  }

  const resetCount = () => {
    count = 0
  }

  return { polling, start, stop, resetCount }
}
