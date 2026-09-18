import type { AxiosError } from 'axios'

/** 后端统一响应错误体（code/message） */
interface ApiErrorBody {
  code?: number
  message?: string
}

/**
 * 从 axios 错误中提取用户可读信息（与 useSettingsForm.getErrorMessage 语义一致）：
 * - 4003（非管理员）固定文案；
 * - 其余业务错误优先展示后端 message（如 4000 校验失败）；
 * - 网络/未知错误回退 fallback。
 */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  const body = (error as AxiosError<ApiErrorBody>)?.response?.data
  if (body?.code === 4003) {
    return '需要管理员权限'
  }
  return body?.message || fallback
}
