/**
 * useReviewActions 审阅动作路由测试.
 * 覆盖：分工章节（有 assignment id）→ approve/reject 走 assignment review 并刷新；
 *      AI 章节（无 assignment id）→ 走 workflow confirm-review 原链路.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({ default: {} }))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))
vi.mock('@/api', () => ({
  confirmReview: vi.fn(),
  approveAssignment: vi.fn(),
  rejectAssignment: vi.fn(),
}))

import { confirmReview, approveAssignment, rejectAssignment } from '@/api'
import { useReviewActions } from '@/views/review/composables/useReviewActions'

const mkRes = (data: unknown, code = 0) => ({ data: { code, data } })

function setup(over: {
  assignmentId?: string | null
  refresh?: ReturnType<typeof vi.fn>
} = {}) {
  const refresh = over.refresh ?? vi.fn().mockResolvedValue(undefined)
  const feedback = { 2: '修改' }
  const actions = useReviewActions({
    projectId: 'p1',
    getActiveChapter: () => '2.1',
    getReviewFeedback: () => feedback,
    setReviewFeedback: (v) => Object.assign(feedback, v),
    setExportStatus: vi.fn(),
    setExportStorageKey: vi.fn(),
    pollUntil: vi.fn(),
    getAssignmentId: () => (over.assignmentId === undefined ? 'a21' : over.assignmentId),
    refreshDivisionData: refresh,
  })
  return { actions, refresh }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(approveAssignment).mockResolvedValue(mkRes(null) as never)
  vi.mocked(rejectAssignment).mockResolvedValue(mkRes(null) as never)
  vi.mocked(confirmReview).mockResolvedValue(mkRes(null) as never)
})

describe('useReviewActions', () => {
  it('分工章节通过：走 assignment 审核（不回写事件由后端完成），并刷新数据', async () => {
    const { actions, refresh } = setup({ assignmentId: 'a21' })
    await actions.handleApprove()
    expect(approveAssignment).toHaveBeenCalledWith('p1', 'a21')
    expect(confirmReview).not.toHaveBeenCalled()
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('分工章节打回：走 assignment 打回并刷新', async () => {
    const { actions, refresh } = setup({ assignmentId: 'a21' })
    await actions.handleReject('请补充验收标准')
    expect(rejectAssignment).toHaveBeenCalledWith('p1', 'a21', '请补充验收标准')
    expect(confirmReview).not.toHaveBeenCalled()
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('AI 章节（无 assignment）：通过走 confirmReview 全量审阅', async () => {
    const { actions } = setup({ assignmentId: null })
    await actions.handleApprove()
    expect(confirmReview).toHaveBeenCalledWith('p1', { action: 'approved' })
    expect(approveAssignment).not.toHaveBeenCalled()
  })

  it('AI 章节（无 assignment）：打回走 confirmReview feedback 意见', async () => {
    const { actions } = setup({ assignmentId: null })
    await actions.handleReject('补充评分点')
    expect(confirmReview).toHaveBeenCalledWith('p1', { action: 'feedback', feedback: { '2.1': '补充评分点' } })
    expect(rejectAssignment).not.toHaveBeenCalled()
  })
})
