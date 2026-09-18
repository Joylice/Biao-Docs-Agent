/**
 * useServerAnnotations 后端批注数据域测试（2026-09-03 编辑器批注同源改造）.
 *
 * 覆盖重点：
 * - load：从 /chapters/{no}/annotations 拉取并映射为面板模型（quote/resolved/author）
 * - addComment：携带当前编辑器选区 {from,to,text} 调 createChapterAnnotation；
 *   无选区（整章留言）时 selection=null
 * - deleteComment / resolveComment / reopenComment：调后端并本地同步
 * - chapterNo 切换自动重载
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref, shallowRef } from 'vue'
import type { Editor } from '@tiptap/core'

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))
vi.mock('@/api', () => ({
  fetchChapterAnnotations: vi.fn(),
  createChapterAnnotation: vi.fn(),
  deleteChapterAnnotation: vi.fn(),
  updateAnnotationStatus: vi.fn(),
}))

import {
  fetchChapterAnnotations,
  createChapterAnnotation,
  deleteChapterAnnotation,
  updateAnnotationStatus,
} from '@/api'
import { useServerAnnotations } from '@/composables/useServerAnnotations'

const mkRes = (data: unknown, code = 0) =>
  ({ data: { code, data }, status: 200, statusText: 'OK', headers: {}, config: {} }) as never

/** 最小可编辑 editor mock：支持 selection.from/to、doc.textBetween、isEditable */
const mkEditor = (selection: { from: number; to: number }, text = '选中文字') => ({
  state: {
    selection,
    doc: { textBetween: () => text },
  },
  isEditable: true,
  chain: () => ({
    focus: () => ({ setTextSelection: () => ({ run: () => undefined }) }),
  }),
}) as unknown as Editor

const ANNO = {
  id: 'a1',
  chapter_no: '2.2',
  content: '文字需处理',
  status: 'open',
  selection: { from: 10, to: 20, text: 'test 003 00' },
  created_by: 'u1',
  created_by_name: '审阅人甲',
  created_at: '2026-09-03T12:00:00Z',
  updated_at: null,
}

function setup() {
  const chapterNo = ref('2.2')
  // shallowRef：避免 Vue 深层 UnwrapRef 拆解 Editor（tiptap 接口含循环引用，
  // unwrap 后类型不再等于 Editor），故不可用 ref<Editor>
  const editorRef = shallowRef<Editor | undefined>(undefined)
  const api = useServerAnnotations('p1', chapterNo, () => editorRef.value)
  return { api, chapterNo, editorRef }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useServerAnnotations', () => {
  it('load 拉取后端批注并映射面板模型（quote/resolved/author）', async () => {
    vi.mocked(fetchChapterAnnotations).mockResolvedValue(
      mkRes({ items: [ANNO, { ...ANNO, id: 'a2', status: 'resolved', selection: null }] }),
    )
    const { api } = setup()
    await api.load()
    expect(fetchChapterAnnotations).toHaveBeenCalledWith('p1', '2.2')
    expect(api.filteredComments.value).toHaveLength(2)
    const c0 = api.filteredComments.value[0]
    expect(c0.quote).toBe('test 003 00')
    expect(c0.author).toBe('审阅人甲')
    expect(c0.resolved).toBe(false)
    expect(api.filteredComments.value[1].resolved).toBe(true)
    expect(api.unresolvedCount.value).toBe(1)
  })

  it('load 幂等：二次调用不重复请求；force 强制刷新', async () => {
    vi.mocked(fetchChapterAnnotations).mockResolvedValue(mkRes({ items: [] }))
    const { api } = setup()
    await api.load()
    await api.load()
    expect(fetchChapterAnnotations).toHaveBeenCalledTimes(1)
    await api.load(true)
    expect(fetchChapterAnnotations).toHaveBeenCalledTimes(2)
  })

  it('addComment 携带编辑器选区提交；无选区时 selection=null（整章留言）', async () => {
    vi.mocked(createChapterAnnotation).mockResolvedValue(
      mkRes({ id: 'a9', chapter_no: '2.2', content: '新增', status: 'open', selection: { from: 3, to: 8, text: '选中文字' }, created_by: 'u9', created_by_name: '编制人', created_at: '2026-09-03T12:10:00Z', updated_at: null }),
    )
    const { api, editorRef } = setup()
    editorRef.value = mkEditor({ from: 3, to: 8 })

    await api.addComment('  新增  ')
    expect(createChapterAnnotation).toHaveBeenCalledWith(
      'p1', '2.2', '新增',
      { from: 3, to: 8, text: '选中文字' },
    )
    expect(api.filteredComments.value[0].author).toBe('编制人')

    // 无选中 → 整章留言
    editorRef.value = mkEditor({ from: 0, to: 0 })
    await api.addComment('整章意见')
    expect(createChapterAnnotation).toHaveBeenLastCalledWith(
      'p1', '2.2', '整章意见', null,
    )
  })

  it('deleteComment 调后端并从列表移除', async () => {
    vi.mocked(fetchChapterAnnotations).mockResolvedValue(mkRes({ items: [ANNO] }))
    vi.mocked(deleteChapterAnnotation).mockResolvedValue(mkRes(null))
    const { api } = setup()
    await api.load()
    await api.deleteComment('a1')
    expect(deleteChapterAnnotation).toHaveBeenCalledWith('p1', '2.2', 'a1')
    expect(api.filteredComments.value).toHaveLength(0)
  })

  it('resolve/reopen 切换状态并回滚（后端失败时）', async () => {
    vi.mocked(fetchChapterAnnotations).mockResolvedValue(mkRes({ items: [ANNO] }))
    vi.mocked(updateAnnotationStatus).mockResolvedValue(
      mkRes({ ...ANNO, status: 'resolved' }),
    )
    const { api } = setup()
    await api.load()
    await api.resolveComment('a1')
    expect(updateAnnotationStatus).toHaveBeenCalledWith('p1', '2.2', 'a1', 'resolved')
    expect(api.filteredComments.value[0].resolved).toBe(true)

    vi.mocked(updateAnnotationStatus).mockRejectedValue(new Error('boom'))
    await api.reopenComment('a1')
    // 失败回滚回 resolved
    expect(api.filteredComments.value[0].resolved).toBe(true)
  })

  it('chapterNo 切换自动重载（清空旧批注）', async () => {
    vi.mocked(fetchChapterAnnotations).mockResolvedValue(mkRes({ items: [ANNO] }))
    const { api, chapterNo } = setup()
    await api.load()
    expect(api.filteredComments.value).toHaveLength(1)

    vi.mocked(fetchChapterAnnotations).mockResolvedValue(mkRes({ items: [] }))
    chapterNo.value = '3.1'
    await new Promise((r) => setTimeout(r, 0)) // watch 异步
    expect(api.filteredComments.value).toHaveLength(0)
    expect(fetchChapterAnnotations).toHaveBeenLastCalledWith('p1', '3.1')
  })
})
