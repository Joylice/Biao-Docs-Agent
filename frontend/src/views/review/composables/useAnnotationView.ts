/**
 * useAnnotationView：ReviewView 批注视图模型（从页面组件抽离）。
 *
 * 由 useAnnotations（数据域）派生纯展示计算属性：
 * - annotationCounts / annotatedCount：各章批注数与已批注章节数（进度条）
 * - currentAnnotations / open / resolved / filtered：当前章节批注列表与筛选
 * - annotationMarks：传递给富文本编辑器的标注 marks（selection 定位）
 * - currentSelectionText：当前选区文字提示
 *
 * 依赖注入全部为 getters/Refs，页面持有真实数据源，本 composable 只做派生。
 */
import { computed, type Ref } from 'vue'
import type { AnnotationItem } from '@/types'

export type AnnotationFilter = 'open' | 'resolved' | 'all'

export interface UseAnnotationViewOptions {
  /** 全部章节号（顺序决定进度条统计） */
  chapterKeys: Ref<string[]>
  /** 当前活动章节号 */
  getActiveChapter: () => string
  /** 某章节批注数 */
  getAnnotationCount: (chapterNo: string) => number
  /** 某章节批注列表 */
  getAnnotations: (chapterNo: string) => AnnotationItem[]
  /** 当前选区文字（无选区返回空串） */
  getSelectionText: () => string
  /** 批注列表筛选条件 */
  filter: Ref<AnnotationFilter>
}

export function useAnnotationView(options: UseAnnotationViewOptions) {
  const { chapterKeys, getActiveChapter, getAnnotationCount, getAnnotations, getSelectionText, filter } = options

  /** 各章节批注数映射（ReviewProgressBar / ReviewChapterList 角标） */
  const annotationCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = {}
    chapterKeys.value.forEach((no) => { counts[no] = getAnnotationCount(no) })
    return counts
  })

  /** 已添加批注的章节数（顶部进度条展示） */
  const annotatedCount = computed(
    () => chapterKeys.value.filter((no) => getAnnotationCount(no) > 0).length,
  )

  /** 当前章节全部批注 */
  const currentAnnotations = computed(() => getAnnotations(getActiveChapter()))

  /** 未解决批注数 */
  const openAnnotationCount = computed(
    () => currentAnnotations.value.filter((a) => a.status !== 'resolved').length,
  )

  /** 已解决批注数 */
  const resolvedAnnotationCount = computed(
    () => currentAnnotations.value.filter((a) => a.status === 'resolved').length,
  )

  /** 按筛选条件过滤后的批注列表 */
  const filteredAnnotations = computed(() => {
    if (filter.value === 'all') return currentAnnotations.value
    return currentAnnotations.value.filter((a) =>
      filter.value === 'open' ? a.status !== 'resolved' : a.status === 'resolved',
    )
  })

  /** 编辑器标注 marks：仅保留有选区定位的批注，供 WordEditor :annotations 高亮 */
  const annotationMarks = computed(() =>
    currentAnnotations.value
      .filter((a) => a.selection && a.selection.from != null && a.selection.to != null)
      .map((a) => ({
        id: a.id,
        from: a.selection!.from,
        to: a.selection!.to,
        status: a.status,
      })),
  )

  /** 当前选区文字（批注输入框占位提示） */
  const currentSelectionText = computed(() => getSelectionText())

  return {
    annotationCounts,
    annotatedCount,
    currentAnnotations,
    openAnnotationCount,
    resolvedAnnotationCount,
    filteredAnnotations,
    annotationMarks,
    currentSelectionText,
  }
}
