import { ref } from 'vue'
import type { Ref } from 'vue'

/** 成功态展示时长（ms） */
const SUCCESS_RESET_MS = 1500

export interface UseSuccessButtonReturn {
  /** 异步操作成功后短暂为 true（1.5s 后自动复位） */
  isSuccess: Ref<boolean>
  /**
   * 包裹异步操作：成功（fn 未抛出）置 isSuccess=true 并 1.5s 后复位。
   * 返回是否成功；fn 内部异常会被捕获，业务错误提示由调用方按返回值处理。
   */
  runWithSuccess: (fn: () => Promise<void>) => Promise<boolean>
}

/** 按钮成功反馈：短暂切换 success 样式 + CheckOutlined 图标 */
export function useSuccessButton(): UseSuccessButtonReturn {
  const isSuccess = ref(false)
  let resetTimer: number | null = null

  const clearResetTimer = () => {
    if (resetTimer !== null) {
      window.clearTimeout(resetTimer)
      resetTimer = null
    }
  }

  const runWithSuccess = async (fn: () => Promise<void>): Promise<boolean> => {
    try {
      await fn()
      isSuccess.value = true
      clearResetTimer()
      resetTimer = window.setTimeout(() => {
        isSuccess.value = false
        resetTimer = null
      }, SUCCESS_RESET_MS)
      return true
    } catch {
      return false
    }
  }

  return { isSuccess, runWithSuccess }
}
