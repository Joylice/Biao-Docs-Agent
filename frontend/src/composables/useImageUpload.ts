/**
 * useImageUpload：编辑器内图片上传能力封装（纯函数 composable）。
 *
 * - uploadImage(file)：FormData → POST /projects/{pid}/images，返回图片可访问 URL
 * - uploadProgress：上传进度（0–100）；uploading：是否上传中；error：错误信息
 * - 通过 axios onUploadProgress 回调更新进度；try/catch 写入 error
 * - onUnmounted 时无需特殊清理（无副作用资源）
 *
 * 上传接口可能返回 url / view_url / file_url 之一，按优先级提取。
 */
import { ref, onUnmounted, type Ref } from 'vue'
import api from '@/api/client'
import type { ApiResponse, DocumentItem } from '@/types'

/** 图片上传响应（后端可能返回 url / view_url / file_url 之一，附文档元信息） */
interface ImageUploadResult {
  url?: string
  view_url?: string
  file_url?: string
}

/** 进度回调事件结构（与 documents.ts 的 onUploadProgress 签名一致） */
interface UploadProgressEvent {
  loaded: number
  total?: number
}

/** 从上传响应中提取图片可访问 URL（按优先级取首个非空） */
const extractImageUrl = (data: ImageUploadResult | undefined): string | null => {
  if (!data) return null
  return data.url ?? data.view_url ?? data.file_url ?? null
}

export interface UseImageUploadReturn {
  /** 上传图片，返回可访问 URL；失败时抛出并写入 error */
  uploadImage: (file: File) => Promise<string>
  /** 上传进度 0–100 */
  uploadProgress: Ref<number>
  /** 是否上传中 */
  uploading: Ref<boolean>
  /** 错误信息（无错误为 null） */
  error: Ref<string | null>
  /** 清除错误状态 */
  clearError: () => void
}

/**
 * 图片上传 composable。
 * @param projectId 项目 ID（响应式引用，可为 undefined —— 缺失时上传抛错）
 */
export function useImageUpload(projectId: Ref<string | undefined>): UseImageUploadReturn {
  const uploading = ref(false)
  const uploadProgress = ref(0)
  const error = ref<string | null>(null)

  const uploadImage = async (file: File): Promise<string> => {
    const pid = projectId.value
    if (!pid) {
      const msg = '缺少 projectId，无法上传图片'
      error.value = msg
      throw new Error(msg)
    }

    uploading.value = true
    error.value = null
    uploadProgress.value = 0

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await api.post<ApiResponse<ImageUploadResult & Partial<DocumentItem>>>(
        `/projects/${pid}/images`,
        formData,
        {
          onUploadProgress: (event: UploadProgressEvent) => {
            if (event.total && event.total > 0) {
              uploadProgress.value = Math.round((event.loaded / event.total) * 100)
            }
          },
        },
      )

      const url = extractImageUrl(res.data.data)
      if (!url) {
        const msg = '上传成功但响应缺少图片地址'
        error.value = msg
        throw new Error(msg)
      }
      uploadProgress.value = 100
      return url
    } catch (e) {
      // 已在上方设置具体错误时保留，否则写入通用信息
      if (!error.value) {
        error.value = e instanceof Error ? e.message : '图片上传失败'
      }
      throw e
    } finally {
      uploading.value = false
    }
  }

  const clearError = () => {
    error.value = null
  }

  onUnmounted(() => {
    // 无定时器/监听需清理，仅复位状态
    uploading.value = false
    uploadProgress.value = 0
  })

  return { uploadImage, uploadProgress, uploading, error, clearError }
}
