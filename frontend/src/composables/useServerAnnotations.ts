/**
 * useServerAnnotations：编辑器批注后端数据域（2026-09-03 批注同源改造）.
 *
 * 背景：分工编辑器（WordEditorPage）批注面板原为 localStorage 纯本地演示（useComments），
 * 与审阅页批注（后端 chapter_annotations 表，/chapters/{no}/annotations）完全隔离 →
 * 审阅批注在分工对应章节查不到。本 composable 将编辑器批注接到同一后端表。
 *
 * 接口对齐 useComments（filteredComments/activeCommentId/filter/unresolvedCount/
 * addComment/deleteComment/resolveComment/reopenComment/scrollToComment），
 * 使 WordEditorComments 面板低侵入切换数据源。后端模型无回复（replies）字段，
 * 故返回模型统一置空 replies（回复线程降级为普通批注，与审阅页一致）。
 */
import { ref, computed, watch, unref } from 'vue'
import type { Editor } from '@tiptap/core'
import type { Ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  fetchChapterAnnotations,
  createChapterAnnotation,
  deleteChapterAnnotation,
  updateAnnotationStatus,
} from '@/api'
import type { AnnotationItem } from '@/types'

/** 面板展示模型（兼容 WordEditorComments 旧模板字段） */
export interface CommentView {
  id: string
  /** 批注引用的文本（selection.text，可为空） */
  quote: string
  content: string
  author: string
  /** epoch ms */
  createdAt: number
  updatedAt: number
  resolved: boolean
  replies: never[]
  /** 文档内位置（selection.from，用于跳转） */
  position?: number
}

function toView(a: AnnotationItem): CommentView {
  return {
    id: a.id,
    quote: a.selection?.text || '',
    content: a.content,
    author: a.created_by_name || '未知用户',
    createdAt: a.created_at ? Date.parse(a.created_at) || Date.now() : Date.now(),
    updatedAt: a.updated_at ? Date.parse(a.updated_at) || Date.now() : Date.now(),
    resolved: a.status === 'resolved',
    replies: [],
    position: a.selection?.from,
  }
}

export function useServerAnnotations(
  projectId: string,
  chapterNo: string | Ref<string>,
  editor: () => Editor | undefined,
) {
  /** 章节号归一（支持响应式：切换章节自动重载） */
  const chapterNoRef = typeof chapterNo === 'string' ? ref(chapterNo) : chapterNo
  const chapterNoOf = () => unref(chapterNoRef)

  const comments = ref<CommentView[]>([])
  const loading = ref(false)
  const loaded = ref(false)

  const activeCommentId = ref<string | null>(null)
  const filter = ref<'all' | 'unresolved' | 'resolved'>('all')

  const filteredComments = computed(() => {
    if (filter.value === 'all') return comments.value
    if (filter.value === 'resolved') return comments.value.filter((c) => c.resolved)
    return comments.value.filter((c) => !c.resolved)
  })

  const unresolvedCount = computed(
    () => comments.value.filter((c) => !c.resolved).length,
  )

  /** 拉取后端批注（幂等：已加载不重复请求） */
  const load = async (force = false) => {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const res = await fetchChapterAnnotations(projectId, chapterNoOf())
      if (res.data?.code === 0) {
        comments.value = (res.data.data?.items || []).map(toView)
        loaded.value = true
      }
    } catch {
      message.error('批注加载失败')
    } finally {
      loading.value = false
    }
  }

  /** 添加批注（基于当前选中文本；无选中则整章留言） */
  const addComment = async (content: string): Promise<CommentView | null> => {
    const text = content.trim()
    if (!text) return null
    const ed = editor()
    const { from, to } = ed?.state.selection ?? { from: 0, to: 0 }
    const hasSelection = ed && from !== to
    const selection = hasSelection
      ? { from, to, text: ed!.state.doc.textBetween(from, to, ' ') }
      : null
    try {
      const res = await createChapterAnnotation(projectId, chapterNoOf(), text, selection)
      if (res.data?.code === 0 && res.data.data) {
        const view = toView(res.data.data)
        comments.value.unshift(view)
        activeCommentId.value = view.id
        loaded.value = true
        return view
      }
      return null
    } catch {
      message.error('批注添加失败')
      return null
    }
  }

  /** 删除批注（作者/负责人） */
  const deleteComment = async (id: string) => {
    try {
      const res = await deleteChapterAnnotation(projectId, chapterNoOf(), id)
      if (res.data?.code === 0) {
        comments.value = comments.value.filter((c) => c.id !== id)
        if (activeCommentId.value === id) activeCommentId.value = null
      }
    } catch {
      message.error('批注删除失败')
    }
  }

  /** 状态切换 open ↔ resolved（解决/重新打开） */
  const setResolved = async (id: string, resolved: boolean) => {
    const comment = comments.value.find((c) => c.id === id)
    if (!comment) return
    const status = resolved ? 'resolved' : 'open'
    comment.resolved = resolved
    try {
      const res = await updateAnnotationStatus(projectId, chapterNoOf(), id, status)
      if (res.data?.code === 0 && res.data.data) {
        Object.assign(comment, toView(res.data.data))
      }
    } catch {
      comment.resolved = !resolved
      message.error('批注状态更新失败')
    }
  }

  const resolveComment = (id: string) => setResolved(id, true)
  const reopenComment = (id: string) => setResolved(id, false)

  /** 跳转到批注位置（有 selection.from 时聚焦选中；无选区仅高亮） */
  const scrollToComment = (id: string) => {
    const comment = comments.value.find((c) => c.id === id)
    const ed = editor()
    activeCommentId.value = id
    if (!comment || !ed) return
    if (comment.position != null && ed.isEditable) {
      try {
        ed.chain().focus().setTextSelection(comment.position).run()
      } catch {
        /* 只读/位置失效时忽略跳转 */
      }
    }
  }

  const clearAll = () => {
    comments.value = []
    activeCommentId.value = null
    loaded.value = false
  }

  watch(
    () => unref(chapterNoRef),
    () => {
      comments.value = []
      loaded.value = false
      activeCommentId.value = null
      load()
    },
  )

  return {
    comments,
    filteredComments,
    activeCommentId,
    filter,
    unresolvedCount,
    loading,
    loaded,
    load,
    addComment,
    deleteComment,
    resolveComment,
    reopenComment,
    scrollToComment,
    clearAll,
  }
}
