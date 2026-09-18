/**
 * useReviewState 审阅状态融合逻辑测试.
 * 覆盖：分工模式（提审章节进审阅页）/ AI 模式两种数据口径的切换，
 *      审阅单元、状态映射、动作定位（assignment id）、标题/提交人解析.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

// 阻断 client 链路（引 router/ui store 的 window 依赖）
vi.mock('@/api/client', () => ({ default: {} }))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))
vi.mock('@/api', () => ({
  fetchWorkflowStatus: vi.fn(),
  fetchChapterAssignments: vi.fn(),
  fetchDisqualificationRisks: vi.fn(),
}))

import { fetchWorkflowStatus, fetchChapterAssignments } from '@/api'
import { useReviewState } from '@/views/review/composables/useReviewState'
import type { WorkflowStatus, AssignmentNode } from '@/types'

const mkRes = (data: unknown, code = 0) => ({ data: { code, data } })

const OUTLINE = [
  { chapter_no: '1', title: '第一章', sections: ['1.1 建设目标', '1.2 建设内容', '1.3 总体架构', '1.4 实施路径'] },
]

const TREE: AssignmentNode[] = [
  {
    id: null,
    chapter_no: '1',
    title: '第一章',
    assignee_id: null,
    assignee_name: null,
    status: 'approved',
    children: [
      { id: 'a11', chapter_no: '1.1', title: '1.1 建设目标', assignee_id: 'u2', assignee_name: '成员乙', status: 'approved', submitted_by_name: '成员乙' },
      { id: 'a12', chapter_no: '1.2', title: '1.2 建设内容', assignee_id: 'u2', assignee_name: '成员乙', status: 'submitted', submitted_by_name: '成员乙' },
      { id: 'a13', chapter_no: '1.3', title: '1.3 总体架构', assignee_id: 'u2', assignee_name: '成员乙', status: 'rejected', submitted_by_name: '成员乙' },
      { id: 'a14', chapter_no: '1.4', title: '1.4 实施路径', assignee_id: 'u2', assignee_name: '成员乙', status: 'pending', submitted_by_name: '成员乙' },
    ],
  },
]

function setup(statusRes: Partial<WorkflowStatus> = {}) {
  vi.mocked(fetchWorkflowStatus).mockResolvedValue(
    mkRes({ phase: 'division', outline: OUTLINE, chapters: {}, review_feedback: {}, export_status: '', ...statusRes }) as never,
  )
  const state = useReviewState('p1')
  return state
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchChapterAssignments).mockResolvedValue(mkRes({ items: TREE }) as never)
})

describe('useReviewState', () => {
  it('AI 模式（无分工）：审阅单元 = state.chapters 章级', async () => {
    vi.mocked(fetchChapterAssignments).mockResolvedValue(mkRes({ items: [] }) as never)
    const s = setup({ chapters: { '2': '第二章内容' } })
    const data = await s.fetchStatus()
    if (data) s.applyStatus(data) // 与页面一致：fetch → apply 写入 chapters
    await s.fetchAssignments()
    expect(s.hasDivision.value).toBe(false)
    expect(s.chapterKeys.value).toEqual(['2'])
    expect(s.rawStatusOf('2')).toBeNull()
    expect(s.assignmentIdOf('2')).toBeNull()
    expect(s.formalChapterKeys.value).toEqual(['2'])
  })

  it('分工模式：fetchAssignments 后审阅单元切换为分工子节（提审章节可见）', async () => {
    const s = setup()
    await s.fetchAssignments()
    expect(s.hasDivision.value).toBe(true)
    expect(s.chapterKeys.value).toEqual(['1.1', '1.2', '1.3', '1.4'])
    // 提审(submitted)章节出现在审阅单元 → 解决「提审后页面为空」
    expect(s.rawStatusOf('1.2')).toBe('submitted')
    expect(s.assignmentIdOf('1.2')).toBe('a12')
    // 章聚合行无 id → 不可直接审
    expect(s.assignmentIdOf('1')).toBeNull()
    // UI 三态映射
    expect(s.chapterStatuses.value['1.1']).toBe('approved')
    expect(s.chapterStatuses.value['1.2']).toBe('pending') // submitted → 待审
    expect(s.chapterStatuses.value['1.3']).toBe('rejected')
    expect(s.chapterStatuses.value['1.4']).toBe('pending')
    expect(s.approvedCount.value).toBe(1)
    expect(s.rejectedCount.value).toBe(1)
    expect(s.submitterOf('1.1')).toBe('成员乙')
    expect(s.titleOf('1.2')).toBe('1.2 建设内容')
    expect(s.titleOf('1')).toBe('第一章')
  })

  it('分工模式但无 state.chapters（未回写）时 formalChapterKeys 为空 → 全文/导出不可用', async () => {
    const s = setup()
    await s.fetchAssignments()
    expect(s.formalChapterKeys.value).toEqual([])
  })

  it('分工模式 fetchAssignments 失败时降级不清空（保留空树，AI 判定不受影响）', async () => {
    vi.mocked(fetchChapterAssignments).mockRejectedValue(new Error('boom'))
    const s = setup()
    await s.fetchAssignments()
    expect(s.hasDivision.value).toBe(false)
    expect(s.chapterKeys.value).toEqual([])
  })
})
