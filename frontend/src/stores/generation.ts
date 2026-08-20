/** 方案生成状态管理（跨页面共享） */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { OutlineItem, WorkflowStatus, AssignmentNode } from '@/types'

export const useGenerationStore = defineStore('generation', () => {
  /* ---------------- 工作流状态 ---------------- */
  const phase = ref<string>('init')
  const interruptType = ref<string>('')
  const progress = ref(0)
  const currentChapter = ref('')

  /* ---------------- 大纲与章节内容 ---------------- */
  const outline = ref<OutlineItem[]>([])
  const chapters = ref<Record<string, string>>({})

  /* ---------------- 分工映射 ---------------- */
  const assignmentMap = ref<Map<string, AssignmentNode>>(new Map())

  /* ---------------- 生成状态 ---------------- */
  const generating = ref(false)
  const generated = ref(false)
  const wsError = ref('')

  /* ---------------- 计算属性 ---------------- */
  const isComplete = computed(() => progress.value >= 1 || generated.value)
  const chapterCount = computed(() => outline.value.length)
  const generatedChapterCount = computed(() =>
    Object.values(chapters.value).filter((c) => c && c.length > 0).length,
  )

  /* ---------------- 状态更新 ---------------- */
  const updateFromStatus = (status: WorkflowStatus) => {
    phase.value = status.phase || 'init'
    interruptType.value = status.interrupt?.type || ''
    progress.value = status.progress || 0
    if (status.outline?.length) outline.value = status.outline
    if (status.chapters) chapters.value = status.chapters
    if (status.progress >= 0.75) generated.value = true
    if (status.current_chapter) currentChapter.value = status.current_chapter
  }

  const updateChapterContent = (chapterNo: string, content: string) => {
    chapters.value[chapterNo] = content
  }

  const appendChapterDelta = (chapterNo: string, delta: string) => {
    chapters.value[chapterNo] = (chapters.value[chapterNo] || '') + delta
  }

  const setAssignmentMap = (map: Map<string, AssignmentNode>) => {
    assignmentMap.value = map
  }

  const markGenerating = () => {
    generating.value = true
    generated.value = false
  }

  const markGenerated = () => {
    generated.value = true
    generating.value = false
    progress.value = 1
    wsError.value = ''
  }

  const reset = () => {
    phase.value = 'init'
    interruptType.value = ''
    progress.value = 0
    currentChapter.value = ''
    outline.value = []
    chapters.value = {}
    assignmentMap.value = new Map()
    generating.value = false
    generated.value = false
    wsError.value = ''
  }

  return {
    phase,
    interruptType,
    progress,
    currentChapter,
    outline,
    chapters,
    assignmentMap,
    generating,
    generated,
    wsError,
    isComplete,
    chapterCount,
    generatedChapterCount,
    updateFromStatus,
    updateChapterContent,
    appendChapterDelta,
    setAssignmentMap,
    markGenerating,
    markGenerated,
    reset,
  }
})
