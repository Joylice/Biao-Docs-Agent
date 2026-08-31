import { ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchChapterAnnotations,
  createChapterAnnotation,
  deleteChapterAnnotation,
  updateAnnotationStatus,
} from '@/api'
import type { AnnotationItem } from '@/types'

interface AnnotationSelection {
  from: number
  to: number
  text: string
}

/**
 * 章节批注域：按章节懒加载、增删、状态切换、本地 patch 合并。
 * newAnnotation 为输入框双向绑定源，随父组件模板 v-model 使用。
 */
export function useAnnotations(projectId: string) {
  const annotationMap = ref<Record<string, AnnotationItem[]>>({})
  const annotationLoaded = ref<Record<string, boolean>>({})
  const annotationsLoading = ref(false)
  const newAnnotation = ref('')
  const addingAnnotation = ref(false)
  /** 当前选区（由富文本编辑器设置） */
  const currentSelection = ref<AnnotationSelection | null>(null)

  const annotationListOf = (chapterNo: string): AnnotationItem[] => annotationMap.value[chapterNo] || []
  const annotationCountOf = (chapterNo: string): number => annotationListOf(chapterNo).length

  const loadAnnotations = async (chapterNo: string) => {
    if (annotationLoaded.value[chapterNo]) return
    annotationsLoading.value = true
    try {
      const res = await fetchChapterAnnotations(projectId, chapterNo)
      if (res.data?.code === 0) {
        annotationMap.value[chapterNo] = res.data.data.items || []
        annotationLoaded.value[chapterNo] = true
      }
    } catch { message.error('批注加载失败') }
    finally { annotationsLoading.value = false }
  }

  const addAnnotation = async (chapterNo: string) => {
    const content = newAnnotation.value.trim()
    if (!chapterNo || !content) return
    addingAnnotation.value = true
    try {
      const res = await createChapterAnnotation(
        projectId,
        chapterNo,
        content,
        currentSelection.value,
      )
      if (res.data?.code === 0) {
        newAnnotation.value = ''
        currentSelection.value = null
        annotationLoaded.value[chapterNo] = false
        await loadAnnotations(chapterNo)
      }
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      message.error(status === 403 ? '无该章节批注权限' : '批注添加失败')
    } finally { addingAnnotation.value = false }
  }

  const deleteAnnotation = async (chapterNo: string, annotationId: string) => {
    try {
      const res = await deleteChapterAnnotation(projectId, chapterNo, annotationId)
      if (res.data?.code === 0) {
        annotationMap.value[chapterNo] = (annotationMap.value[chapterNo] || []).filter(
          (it) => it.id !== annotationId,
        )
        message.success('批注已删除')
      }
    } catch { message.error('批注删除失败') }
  }

  /** 切换批注状态（open ↔ resolved） */
  const toggleAnnotationStatus = async (chapterNo: string, annotationId: string) => {
    const items = annotationMap.value[chapterNo] || []
    const item = items.find((it) => it.id === annotationId)
    if (!item) return
    const newStatus = item.status === 'open' ? 'resolved' : 'open'
    // 乐观更新
    item.status = newStatus
    try {
      const res = await updateAnnotationStatus(projectId, chapterNo, annotationId, newStatus)
      if (res.data?.code === 0) {
        Object.assign(item, res.data.data)
        message.success(newStatus === 'resolved' ? '批注已标记解决' : '批注已重新打开')
      }
    } catch {
      // 回滚
      item.status = item.status === 'open' ? 'resolved' : 'open'
      message.error('状态更新失败')
    }
  }

  /** 批注编辑弹窗保存成功：以 patch 合并本地批注列表 */
  const mergeUpdatedAnnotation = (chapterNo: string, annotationId: string, patch: Partial<AnnotationItem>) => {
    const items = annotationMap.value[chapterNo] || []
    const idx = items.findIndex((it) => it.id === annotationId)
    if (idx >= 0) items[idx] = { ...items[idx], ...patch }
  }

  /** 设置当前选区（由编辑器选区变化时调用） */
  const setSelection = (sel: AnnotationSelection | null) => {
    currentSelection.value = sel
  }

  return {
    annotationsLoading,
    newAnnotation,
    addingAnnotation,
    currentSelection,
    annotationMap,
    annotationLoaded,
    annotationListOf,
    annotationCountOf,
    loadAnnotations,
    addAnnotation,
    deleteAnnotation,
    toggleAnnotationStatus,
    mergeUpdatedAnnotation,
    setSelection,
  }
}
