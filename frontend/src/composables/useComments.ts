/**
 * 批注管理 composable
 * - 管理批注列表（增删改查）
 * - 选中文字添加批注
 * - 批注回复
 * - 批注解决/重新打开
 * - 本地存储（localStorage）
 */
import { ref, computed, watch } from 'vue'
import type { Editor } from '@tiptap/core'

/** 批注回复 */
export interface CommentReply {
  id: string
  author: string
  content: string
  createdAt: number
}

/** 批注 */
export interface Comment {
  id: string
  /** 批注引用的文本 */
  quote: string
  /** 批注内容 */
  content: string
  /** 作者 */
  author: string
  /** 创建时间 */
  createdAt: number
  /** 更新时间 */
  updatedAt: number
  /** 是否已解决 */
  resolved: boolean
  /** 解决时间 */
  resolvedAt?: number
  /** 回复列表 */
  replies: CommentReply[]
  /** 在文档中的位置（用于跳转，可选） */
  position?: number
}

/** 生成唯一 ID */
function generateId(): string {
  return `comment-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/**
 * 使用批注管理
 * @param editor 编辑器实例
 * @param storageKey 本地存储 key
 */
export function useComments(editor: () => Editor | undefined, storageKey = 'editor-comments') {
  /* 批注列表 */
  const comments = ref<Comment[]>([])

  /* 当前选中的批注 ID */
  const activeCommentId = ref<string | null>(null)

  /* 筛选状态：all / unresolved / resolved */
  const filter = ref<'all' | 'unresolved' | 'resolved'>('all')

  /* 从本地存储加载 */
  const loadFromStorage = () => {
    try {
      const stored = localStorage.getItem(storageKey)
      if (stored) {
        comments.value = JSON.parse(stored)
      }
    } catch {
      // 忽略加载错误
    }
  }

  /* 保存到本地存储 */
  const saveToStorage = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(comments.value))
    } catch {
      // 忽略保存错误
    }
  }

  /* 监听变化自动保存 */
  watch(comments, saveToStorage, { deep: true })

  /* 初始化加载 */
  loadFromStorage()

  /* 筛选后的批注列表 */
  const filteredComments = computed(() => {
    if (filter.value === 'all') return comments.value
    if (filter.value === 'resolved') return comments.value.filter((c) => c.resolved)
    return comments.value.filter((c) => !c.resolved)
  })

  /* 未解决批注数量 */
  const unresolvedCount = computed(() => comments.value.filter((c) => !c.resolved).length)

  /**
   * 添加批注（基于当前选中文本）
   */
  const addComment = (content: string, author = '当前用户'): Comment | null => {
    const ed = editor()
    if (!ed) return null

    const { from, to } = ed.state.selection
    if (from === to) {
      // 没有选中文本，不允许添加批注
      return null
    }

    const quote = ed.state.doc.textBetween(from, to, ' ')
    const comment: Comment = {
      id: generateId(),
      quote,
      content,
      author,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      resolved: false,
      replies: [],
      position: from,
    }

    comments.value.unshift(comment)
    activeCommentId.value = comment.id
    return comment
  }

  /**
   * 更新批注内容
   */
  const updateComment = (id: string, content: string) => {
    const comment = comments.value.find((c) => c.id === id)
    if (comment) {
      comment.content = content
      comment.updatedAt = Date.now()
    }
  }

  /**
   * 删除批注
   */
  const deleteComment = (id: string) => {
    const index = comments.value.findIndex((c) => c.id === id)
    if (index !== -1) {
      comments.value.splice(index, 1)
      if (activeCommentId.value === id) {
        activeCommentId.value = null
      }
    }
  }

  /**
   * 解决批注
   */
  const resolveComment = (id: string) => {
    const comment = comments.value.find((c) => c.id === id)
    if (comment) {
      comment.resolved = true
      comment.resolvedAt = Date.now()
      comment.updatedAt = Date.now()
    }
  }

  /**
   * 重新打开批注
   */
  const reopenComment = (id: string) => {
    const comment = comments.value.find((c) => c.id === id)
    if (comment) {
      comment.resolved = false
      comment.resolvedAt = undefined
      comment.updatedAt = Date.now()
    }
  }

  /**
   * 添加回复
   */
  const addReply = (commentId: string, content: string, author = '当前用户') => {
    const comment = comments.value.find((c) => c.id === commentId)
    if (comment) {
      const reply: CommentReply = {
        id: generateId(),
        author,
        content,
        createdAt: Date.now(),
      }
      comment.replies.push(reply)
      comment.updatedAt = Date.now()
    }
  }

  /**
   * 删除回复
   */
  const deleteReply = (commentId: string, replyId: string) => {
    const comment = comments.value.find((c) => c.id === commentId)
    if (comment) {
      const index = comment.replies.findIndex((r) => r.id === replyId)
      if (index !== -1) {
        comment.replies.splice(index, 1)
        comment.updatedAt = Date.now()
      }
    }
  }

  /**
   * 跳转到批注位置
   */
  const scrollToComment = (id: string) => {
    const comment = comments.value.find((c) => c.id === id)
    const ed = editor()
    if (!comment || !ed || comment.position == null) return

    try {
      ed.chain().focus().setTextSelection(comment.position).run()
      // 滚动到视图
      const dom = ed.view.dom
      const selected = dom.querySelector('.ProseMirror-selectednode, [data-selected]')
      selected?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } catch {
      // 忽略跳转错误
    }
    activeCommentId.value = id
  }

  /**
   * 清空所有批注
   */
  const clearAll = () => {
    comments.value = []
    activeCommentId.value = null
  }

  /**
   * 导出批注为 JSON
   */
  const exportComments = (): string => {
    return JSON.stringify(comments.value, null, 2)
  }

  /**
   * 从 JSON 导入批注
   */
  const importComments = (json: string): boolean => {
    try {
      const data = JSON.parse(json)
      if (Array.isArray(data)) {
        comments.value = data
        return true
      }
    } catch {
      // 忽略解析错误
    }
    return false
  }

  return {
    // 状态
    comments,
    filteredComments,
    activeCommentId,
    filter,
    unresolvedCount,
    // 操作
    addComment,
    updateComment,
    deleteComment,
    resolveComment,
    reopenComment,
    addReply,
    deleteReply,
    scrollToComment,
    clearAll,
    exportComments,
    importComments,
  }
}
