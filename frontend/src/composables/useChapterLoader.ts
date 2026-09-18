/**
 * useChapterLoader：章节内容加载逻辑.
 *
 * 职责：并行 fetch content + assignments + project + members，
 * content_html 优先，否则 markdownToHtml(content)；
 * 标题从分工树查找；owner/任务数据经 onLoaded 回调。
 *
 * 拆自 useChapterPersistence（Phase 5 composable 职责拆分）.
 */
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { markdownToHtml } from '@/utils/markdown-converter'
import type { ProposalContent } from '@/types/dsl'
import {
  fetchChapterContent,
  fetchChapterAssignments,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import type { AssignmentNode, AssignmentItem } from '@/types'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'

/** 加载完成回调数据（供页面装配任务状态等） */
export interface ChapterLoadData {
  chapterTitle: string
  projectOwnerId: string
  currentTask: AssignmentItem | null
  assignments: AssignmentNode[]
  isProjectMember: boolean
}

/** 在分工树中递归查找 chapter_no 对应的标题 */
export const findChapterTitle = (nodes: AssignmentNode[], target: string): string => {
  for (const node of nodes) {
    if (node.chapter_no === target) return node.title
    if (node.children?.length) {
      const found = findChapterTitle(node.children, target)
      if (found) return found
    }
  }
  return ''
}

/** 将分工树扁平化为任务列表 */
export const flattenAssignments = (nodes: AssignmentNode[]): AssignmentItem[] => {
  const flat: AssignmentItem[] = []
  const walk = (list: AssignmentNode[]) => {
    list.forEach((node) => {
      if (node.id) flat.push(node as unknown as AssignmentItem)
      if (node.children?.length) walk(node.children)
    })
  }
  walk(nodes)
  return flat
}

export interface UseChapterLoaderOptions {
  projectId: string
  chapterNo: string
  onLoaded?: (data: ChapterLoadData) => void
}

export interface UseChapterLoaderReturn {
  loading: import('vue').Ref<boolean>
  /** 初始内容（Phase 3：优先为 DSL JSON，降级为 HTML string） */
  initialContent: import('vue').Ref<string | Record<string, unknown>>
  /** 初始 HTML（向后兼容，只读/分页预览等场景仍需 HTML） */
  initialHtml: import('vue').Ref<string>
  chapterTitle: import('vue').Ref<string>
  /** 设置后用于保存基线对比（由编排层读取） */
  lastSavedHtml: import('vue').Ref<string>
  /** Phase 3：DSL 基线 ref（用于保存时对比 + lastSavedDsl） */
  initialDsl: import('vue').Ref<ProposalContent | null>
  lastSavedDsl: import('vue').Ref<ProposalContent | null>
  loadChapter: () => Promise<void>
}

export function useChapterLoader(options: UseChapterLoaderOptions): UseChapterLoaderReturn {
  const { projectId, chapterNo, onLoaded } = options

  const loading = ref(false)
  const initialContent = ref<string | Record<string, unknown>>('')
  const initialHtml = ref('')
  const chapterTitle = ref('')
  const lastSavedHtml = ref('')
  const initialDsl = ref<ProposalContent | null>(null)
  const lastSavedDsl = ref<ProposalContent | null>(null)

  const loadChapter = async () => {
    loading.value = true
    try {
      // 身份就绪保障（2026-09-03 回归）：编辑器为独立整页路由（不经 AppLayout），
      // 整页刷新 / 深链直入时 currentUserId 为空（初始 ''），会导致 isProjectMember
      // 恒为 false、assignee/owner 判定全部失效，误报「您不是项目成员，仅可查看」。
      // 此处补拉一次 /auth/me；401 由 client 拦截器统一清 token 跳登录，失败不阻断加载。
      if (!currentUserId.value) {
        try {
          await fetchCurrentUserRole()
        } catch {
          // /auth/me 异常（网络等）：保持空身份继续，避免阻断内容展示
        }
      }
      const [contentRes, assignmentsRes, projectRes, membersRes] = await Promise.all([
        fetchChapterContent(projectId, chapterNo),
        fetchChapterAssignments(projectId),
        fetchProject(projectId),
        fetchProjectMembers(projectId),
      ])
      const data = contentRes.data.data

      // Phase 3：优先使用 content_dsl（结构化真源），无则降级到 content_html / Markdown
      const dslData = data?.content_dsl
      if (dslData && typeof dslData === 'object' && (dslData as Record<string, unknown>).blocks) {
        // DSL 优先：转 ProseMirror JSON 供 Tiptap 直接 setContent
        const dsl = dslData as unknown as ProposalContent
        initialDsl.value = dsl
        lastSavedDsl.value = dsl
        // dslToProseMirror 在 useChapterLoader 中延迟导入，避免循环依赖
        // 初始内容设为 DSL 对象，WordEditor.vue 的 watch 会识别并 setContent(JSON)
        const { dslToProseMirror } = await import('@/utils/dsl-converter')
        initialContent.value = dslToProseMirror(dsl)
        // 同时保留 HTML 副本（只读/分页预览/导出等场景仍需 HTML）
        initialHtml.value = data?.content_html || (data?.content ? markdownToHtml(data.content) : '')
        lastSavedHtml.value = initialHtml.value
      } else {
        // 降级：无 DSL → 使用 HTML（content_html 优先，否则 Markdown→HTML）
        initialDsl.value = null
        lastSavedDsl.value = null
        initialHtml.value = data?.content_html || (data?.content ? markdownToHtml(data.content) : '')
        lastSavedHtml.value = initialHtml.value
        initialContent.value = initialHtml.value
      }

      const items = assignmentsRes.data.data?.items ?? []
      const title = findChapterTitle(items, chapterNo)
      chapterTitle.value = title

      const ownerId = projectRes.data.data?.owner_id || ''
      const memberIds = (membersRes.data.data?.items ?? []).map((m) => m.user_id)
      // owner 视为项目内成员（后端 _check_project_member 对 owner 直接放行；
      // 兼容早期创建、owner 未写入成员表的项目数据）
      const isProjectMember =
        memberIds.includes(currentUserId.value) || ownerId === currentUserId.value
      const currentTask = flattenAssignments(items).find((t) => t.chapter_no === chapterNo) || null
      onLoaded?.({
        chapterTitle: title,
        projectOwnerId: ownerId,
        currentTask,
        assignments: items,
        isProjectMember,
      })
    } catch {
      message.error('章节内容加载失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    initialContent,
    initialHtml,
    chapterTitle,
    lastSavedHtml,
    initialDsl,
    lastSavedDsl,
    loadChapter,
  }
}
