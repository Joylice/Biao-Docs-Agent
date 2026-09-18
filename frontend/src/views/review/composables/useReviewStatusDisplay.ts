import { computed, type Ref } from 'vue'

/**
 * 章节状态展示模型（N8 拆分：从 ReviewView 抽出）
 * 根据 hasDivision / rawStatus / chapterStatus 计算展示文本与颜色。
 */
export function useReviewStatusDisplay(deps: {
  hasDivision: Ref<boolean>
  chapterStatuses: Ref<Record<string, string>>
  rawStatusOf: (chapterNo: string) => string | null | undefined
  activeChapter: Ref<string>
}) {
  const { hasDivision, chapterStatuses, rawStatusOf, activeChapter } = deps

  const currentChapterStatus = computed(
    () => chapterStatuses.value[activeChapter.value] || 'pending',
  )

  const currentRawStatus = computed(() => rawStatusOf(activeChapter.value))

  const currentStatusText = computed(() => {
    if (hasDivision.value && currentRawStatus.value) {
      const map: Record<string, string> = {
        pending: '未提审',
        in_progress: '编制中',
        submitted: '待审阅',
        approved: '已通过',
        rejected: '需修改',
      }
      return map[currentRawStatus.value] || '未审阅'
    }
    const map: Record<string, string> = { pending: '未审阅', approved: '已通过', rejected: '需修改' }
    return map[currentChapterStatus.value] || '未审阅'
  })

  const currentStatusColor = computed(() => {
    if (hasDivision.value && currentRawStatus.value) {
      const map: Record<string, string> = {
        pending: 'default',
        in_progress: 'processing',
        submitted: 'blue',
        approved: 'green',
        rejected: 'orange',
      }
      return map[currentRawStatus.value] || 'default'
    }
    const map: Record<string, string> = { pending: 'default', approved: 'green', rejected: 'orange' }
    return map[currentChapterStatus.value] || 'default'
  })

  return {
    currentChapterStatus,
    currentRawStatus,
    currentStatusText,
    currentStatusColor,
  }
}
