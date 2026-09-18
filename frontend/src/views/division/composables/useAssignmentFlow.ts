import { ref, computed, type Ref } from 'vue'
import type {
  AssignmentItem,
  AssignmentNode,
  ProjectMember,
  OutlineItem,
  OutlineSection,
} from '@/types'
import type { DivisionApi, DivisionNotify, AssignRow } from './useDivisionBoard'
import { flattenAssignmentNodes, sectionTitleOf } from './divisionUtils'

/**
 * 分配面板逻辑（N9 拆分：从 useDivisionBoard 抽出）
 * 负责：大纲主干合并分工数据、分配草稿基线、变更计算、推送校验
 */
export function useAssignmentFlow(deps: {
  api: DivisionApi
  notify: DivisionNotify
  projectId: string
  outline: Ref<OutlineItem[]>
  assignTree: Ref<AssignmentNode[]>
  members: Ref<ProjectMember[]>
  loading: Ref<boolean>
  loadError: Ref<string>
  items: Ref<AssignmentItem[]>
}) {
  const { api, notify, projectId, outline, assignTree, members, loadError, items } = deps

  const draftAssignees = ref<Record<string, string | undefined>>({})
  const assigning = ref(false)

  const memberOptions = computed(() =>
    members.value.map((m) => ({
      value: m.user_id,
      label: m.display_name ? `${m.display_name}（${m.email}）` : m.email,
    })),
  )

  const filterMember = (input: string, option: { label: string }) =>
    option.label.toLowerCase().includes(input.toLowerCase())

  const assignRows = computed<AssignRow[]>(() => {
    const flat = flattenAssignmentNodes(assignTree.value)
    const byNo = new Map(flat.map((n) => [n.chapter_no, n]))
    const rows: AssignRow[] = []
    const pushed = new Set<string>()

    const mergeFrom = (no: string, title: string): AssignRow => {
      const a = byNo.get(no)
      return {
        chapter_no: no,
        title,
        id: a?.id ?? undefined,
        assignee_id: a?.assignee_id ?? undefined,
        assignee_name: a?.assignee_name ?? undefined,
        status: a?.status ?? undefined,
      }
    }

    const pushChapter = (chapterNo: string, title: string, sections: OutlineSection[]) => {
      const row = mergeFrom(chapterNo, title)
      const children = sections.map((s, i) => mergeFrom(`${chapterNo}.${i + 1}`, sectionTitleOf(s)))
      const covered = new Set(children.map((c) => c.chapter_no))
      flat.forEach((a) => {
        if (a.chapter_no.startsWith(`${chapterNo}.`) && !covered.has(a.chapter_no)) {
          children.push(mergeFrom(a.chapter_no, a.title))
          covered.add(a.chapter_no)
        }
      })
      row.children = children.length ? children : undefined
      rows.push(row)
      pushed.add(chapterNo)
      children.forEach((c) => pushed.add(c.chapter_no))
    }

    outline.value.forEach((c) => pushChapter(c.chapter_no, c.title, c.sections ?? []))

    assignTree.value.forEach((node) => {
      if (pushed.has(node.chapter_no)) return
      if (node.chapter_no.includes('.') && pushed.has(node.chapter_no.split('.')[0])) return
      const row = mergeFrom(node.chapter_no, node.title)
      const children = (node.children ?? []).map((c) => mergeFrom(c.chapter_no, c.title))
      row.children = children.length ? children : undefined
      rows.push(row)
      pushed.add(node.chapter_no)
      children.forEach((c) => pushed.add(c.chapter_no))
    })

    return rows
  })

  const assignableRows = computed<AssignRow[]>(() =>
    assignRows.value.flatMap((row) => [row, ...(row.children?.length ? row.children : [])]),
  )

  const changedItems = computed(() =>
    assignableRows.value.filter((row) => {
      const next = draftAssignees.value[row.chapter_no]
      return !!next && next !== row.assignee_id
    }),
  )
  const changedCount = computed(() => changedItems.value.length)

  const syncDraftBaseline = (nodes: AssignmentNode[]) => {
    const draft: Record<string, string | undefined> = {}
    const walk = (list: AssignmentNode[]) => {
      list.forEach((node) => {
        draft[node.chapter_no] = node.assignee_id ?? undefined
        if (node.children?.length) walk(node.children)
      })
    }
    walk(nodes)
    draftAssignees.value = draft
  }

  const fetchAssignments = async () => {
    try {
      const { data } = await api.fetchChapterAssignments(projectId)
      if (data.code === 0) {
        const tree: AssignmentNode[] = data.data?.items || []
        assignTree.value = tree
        syncDraftBaseline(tree)
        const flat: AssignmentItem[] = []
        const flatten = (nodes: AssignmentNode[]) => {
          nodes.forEach((node) => {
            if (node.id) {
              flat.push(node as unknown as AssignmentItem)
            }
            if (node.children?.length) flatten(node.children)
          })
        }
        flatten(tree)
        items.value = flat
      }
    } catch {
      loadError.value = '分工数据加载失败'
    }
  }

  const handleAssign = async () => {
    const payload = changedItems.value.map((row) => ({
      chapter_no: row.chapter_no,
      title: row.title,
      assignee_id: draftAssignees.value[row.chapter_no] as string,
    }))
    if (payload.length === 0) return

    const invalid = payload.find((item) => !item.chapter_no || !item.title || !item.assignee_id)
    if (invalid) {
      console.error('[分工推送] 无效条目:', invalid)
      notify.error(`章节「${invalid.chapter_no || '未知'}」信息不完整（标题或负责人为空），无法推送`)
      return
    }

    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
    const invalidUuid = payload.find((item) => !uuidRegex.test(item.assignee_id))
    if (invalidUuid) {
      console.error('[分工推送] 无效 assignee_id:', invalidUuid)
      notify.error(`章节「${invalidUuid.chapter_no}」的负责人ID格式错误，请重新选择负责人`)
      return
    }

    assigning.value = true
    try {
      const { data } = await api.upsertChapterAssignments(projectId, payload)
      if (data.code === 0) {
        await fetchAssignments()
        notify.success(`已推送 ${payload.length} 个章节的分工任务`)
      } else {
        console.error('[分工推送] 后端返回业务错误 code:', data.code, 'message:', data.message)
        const detail = `错误码: ${data.code}，消息: ${data.message || '未知错误'}`
        notify.error(`分工推送失败：${detail}`, 5)
      }
    } catch (err) {
      const e = err as {
        response?: { status?: number; data?: { message?: string; code?: number } }
        message?: string
        request?: unknown
      }
      console.error('[分工推送] 请求异常:', e)
      console.error('[分工推送] 异常 response:', e?.response)
      console.error('[分工推送] 异常 request:', e?.request)

      const status = e?.response?.status
      const body = e?.response?.data
      const msg = body?.message
      const code = body?.code

      let detail = ''
      if (status) detail += `HTTP状态码: ${status}\n`
      if (code) detail += `业务错误码: ${code}\n`
      if (msg) detail += `错误消息: ${msg}\n`
      if (e?.message) detail += `异常消息: ${e.message}\n`
      if (!detail) detail = '未知错误，请查看浏览器控制台日志'

      let friendlyMsg = '分工推送失败'
      if (code === 4004) {
        friendlyMsg = `负责人不是项目成员：${msg || '请先将该用户添加为项目成员'}`
      } else if (code === 4000) {
        friendlyMsg = `分工数据不完整：${msg || '请检查章节标题和负责人是否已填写'}`
      } else if (status === 500) {
        friendlyMsg = `服务器内部错误（500）：${msg || '请联系管理员查看后端日志'}`
      } else if (status === 401 || status === 403) {
        friendlyMsg = `权限不足（${status}）：请确认您是项目负责人且已登录`
      } else if (msg) {
        friendlyMsg = msg
      }

      notify.error(`${friendlyMsg}\n\n${detail}`, 8)
      console.error('[分工推送] 失败时的 payload:', JSON.stringify(payload, null, 2))
    } finally {
      assigning.value = false
    }
  }

  return {
    draftAssignees,
    assigning,
    memberOptions,
    filterMember,
    assignRows,
    assignableRows,
    changedItems,
    changedCount,
    syncDraftBaseline,
    fetchAssignments,
    handleAssign,
  }
}
