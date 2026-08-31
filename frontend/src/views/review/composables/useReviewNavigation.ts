/**
 * useReviewNavigation：审阅页面章节导航与内容加载 composable
 *
 * 职责：
 * - 章节切换（selectChapter）+ URL同步
 * - 章节富文本HTML加载与缓存（loadChapterHtml/chapterHtmlMap）
 * - 单章/全文预览模式切换
 * - 全文模式滚动联动（IntersectionObserver）
 */
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchChapterContent } from '@/api'
import { markdownToHtml } from '@/utils/markdown-converter'
import type { OutlineNode, RiskItem } from './useReviewState'

export function useReviewNavigation(options: {
  projectId: string
  getChapters: () => Record<string, string>
  getOutline: () => OutlineNode[]
  getRisks: () => Record<string, RiskItem[]>
  loadAnnotations: (chapterNo: string) => void
}) {
  const { projectId, getChapters, getOutline, getRisks, loadAnnotations } = options
  const route = useRoute()
  const router = useRouter()

  /* ---------------- 章节状态 ---------------- */
  const activeChapter = ref('')
  const expandedKeys = ref<string[]>([])
  const chapterHtmlMap = ref<Record<string, string>>({})
  const contentLoading = ref(false)

  /* ---------------- 预览模式 ---------------- */
  const viewMode = ref<'single' | 'full'>('single')
  const fullContentRef = ref<HTMLElement | null>(null)
  let fullObserver: IntersectionObserver | null = null

  /* ---------------- 计算属性 ---------------- */
  const chapterKeys = computed(() => Object.keys(getChapters()))

  const activeChapterTitle = computed(
    () => getOutline().find((c) => c.chapter_no === activeChapter.value)?.title || '',
  )

  const activeChapterRisks = computed<RiskItem[]>(
    () => getRisks()[activeChapter.value] || [],
  )

  const currentHtml = computed(() => chapterHtmlMap.value[activeChapter.value] || '')

  const currentChapterMarkdown = computed(() => getChapters()[activeChapter.value] || '')

  /* ---------------- 章节内容加载 ---------------- */
  const loadChapterHtml = async (chapterNo: string) => {
    if (chapterHtmlMap.value[chapterNo]) return
    contentLoading.value = true
    try {
      const res = await fetchChapterContent(projectId, chapterNo)
      const data = res.data?.data
      if (data?.content_html) {
        chapterHtmlMap.value[chapterNo] = data.content_html
      } else if (data?.content) {
        chapterHtmlMap.value[chapterNo] = markdownToHtml(data.content)
      } else if (getChapters()[chapterNo]) {
        chapterHtmlMap.value[chapterNo] = markdownToHtml(getChapters()[chapterNo])
      }
    } catch {
      if (getChapters()[chapterNo]) {
        chapterHtmlMap.value[chapterNo] = markdownToHtml(getChapters()[chapterNo])
      }
    } finally {
      contentLoading.value = false
    }
  }

  /* ---------------- 章节切换 ---------------- */
  const selectChapter = async (chapterNo: string) => {
    activeChapter.value = chapterNo
    router.replace({ query: { ...route.query, chapter: chapterNo } })

    if (viewMode.value === 'full') {
      const el = document.getElementById(`chapter-${chapterNo}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      return
    }

    loadAnnotations(chapterNo)
    await loadChapterHtml(chapterNo)
  }

  /* ---------------- 全文预览 ---------------- */
  const loadAllChapterHtml = async () => {
    for (const no of chapterKeys.value) {
      if (!chapterHtmlMap.value[no]) {
        await loadChapterHtml(no)
      }
    }
  }

  const startFullObserver = () => {
    if (fullObserver) return
    fullObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          const id = visible[0].target.id
          const chapterNo = id.replace('chapter-', '')
          if (chapterNo && chapterNo !== activeChapter.value) {
            activeChapter.value = chapterNo
            router.replace({ query: { ...route.query, chapter: chapterNo } })
          }
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    )
    chapterKeys.value.forEach((no) => {
      const el = document.getElementById(`chapter-${no}`)
      if (el) fullObserver?.observe(el)
    })
  }

  const stopFullObserver = () => {
    if (fullObserver) {
      fullObserver.disconnect()
      fullObserver = null
    }
  }

  watch(viewMode, async (mode) => {
    if (mode === 'full') {
      await loadAllChapterHtml()
      nextTick(() => startFullObserver())
    } else {
      stopFullObserver()
      if (activeChapter.value) {
        loadAnnotations(activeChapter.value)
        await loadChapterHtml(activeChapter.value)
      }
    }
  })

  onUnmounted(() => {
    stopFullObserver()
  })

  /* ---------------- 清空HTML缓存（内容更新时调用） ---------------- */
  const clearHtmlCache = () => {
    chapterHtmlMap.value = {}
  }

  return {
    // 状态
    activeChapter,
    expandedKeys,
    chapterHtmlMap,
    contentLoading,
    viewMode,
    fullContentRef,
    // 计算属性
    activeChapterTitle,
    activeChapterRisks,
    currentHtml,
    currentChapterMarkdown,
    // 方法
    selectChapter,
    loadChapterHtml,
    clearHtmlCache,
    stopFullObserver,
  }
}
