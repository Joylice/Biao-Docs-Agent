import { ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchChapterAnnotations,
  createChapterAnnotation,
  deleteChapterAnnotation,
} from '@/api'
import type { AnnotationItem } from '@/types'

/**
 * 章节批注域：按章节懒加载、增删、本地 patch 合并。
 * newAnnotation 为输入框双向绑定源，随父组件模板 v-model 使用。
 */
export function useAnnotations(projectId: string) {
  const annotationMap = ref<Record<string, AnnotationItem[]>>({})
  const annotationLoaded = ref<Record<string, boolean>>({})
  const annotationsLoading = ref(false)
  const newAnnotation = ref('')
  const addingAnnotation = ref(false)

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
      const res = await createChapterAnnotation(projectId, chapterNo, content)
      if (res.data?.code === 0) {
        newAnnotation.value = ''
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

  /** 批注编辑弹窗保存成功：以 patch 合并本地批注列表 */
  const mergeUpdatedAnnotation = (chapterNo: string, annotationId: string, patch: Partial<AnnotationItem>) => {
    const items = annotationMap.value[chapterNo] || []
    const idx = items.findIndex((it) => it.id === annotationId)
    if (idx >= 0) items[idx] = { ...items[idx], ...patch }
  }

  return {
    annotationsLoading,
    newAnnotation,
    addingAnnotation,
    annotationListOf,
    annotationCountOf,
    loadAnnotations,
    addAnnotation,
    deleteAnnotation,
    mergeUpdatedAnnotation,
  }
}
