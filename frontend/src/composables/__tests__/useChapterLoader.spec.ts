/**
 * useChapterLoader 加载逻辑测试.
 *
 * 覆盖重点（2026-09-03 回归场景）：
 * - 编辑器页整页刷新 / 深链直入（不经 AppLayout）时 currentUserId 为空，
 *   loadChapter 必须先补拉 /auth/me（fetchCurrentUserRole）再判定成员/分工，
 *   避免把"身份未就绪"误报为"您不是项目成员"。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// stores/currentUser 依赖 api client（client 引 router → window），单测环境 mock 掉
vi.mock('@/api/client', () => ({ default: {} }))

vi.mock('@/api', () => ({
  fetchChapterContent: vi.fn(),
  fetchChapterAssignments: vi.fn(),
  fetchProject: vi.fn(),
  fetchProjectMembers: vi.fn(),
  saveChapterContent: vi.fn(),
}))

// 保留 stores/currentUser 真实模块级 ref（currentUserId），仅替换 fetchCurrentUserRole
vi.mock('@/stores/currentUser', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/stores/currentUser')>()
  return { ...mod, fetchCurrentUserRole: vi.fn() }
})

import { useChapterLoader } from '@/composables/useChapterLoader'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import {
  fetchChapterAssignments,
  fetchChapterContent,
  fetchProject,
  fetchProjectMembers,
} from '@/api'

const UID = {
  owner: '11111111-1111-4111-8111-111111111111',
  member: '22222222-2222-4222-8222-222222222222',
}

/** axios 响应外壳（vi.mocked 需要 AxiosResponse 形状；cast 掉具体泛型） */
const mkRes = (data: unknown, code = 0) =>
  ({ data: { code, data }, status: 200, statusText: 'OK', headers: {}, config: {} }) as never

const tree = [
  {
    chapter_no: '2',
    title: '第二章',
    id: 't1',
    assignee_id: UID.member,
    assignee_name: '成员乙',
    status: 'submitted',
    children: [
      {
        chapter_no: '2.1',
        title: '2.1 总体架构',
        id: 't1-1',
        assignee_id: UID.member,
        assignee_name: '成员乙',
        status: 'submitted',
        children: [],
      },
    ],
  },
]

const members = [
  { user_id: UID.owner, email: 'owner@x.com', display_name: '负责人甲', role: 'owner' },
  { user_id: UID.member, email: 'member@x.com', display_name: '成员乙', role: 'member' },
]

function mockApiOk() {
  vi.mocked(fetchChapterContent).mockResolvedValue(
    mkRes({ content_html: '<p>内容</p>', content: '内容' }),
  )
  vi.mocked(fetchChapterAssignments).mockResolvedValue(mkRes({ items: tree }))
  vi.mocked(fetchProject).mockResolvedValue(mkRes({ owner_id: UID.owner }))
  vi.mocked(fetchProjectMembers).mockResolvedValue(mkRes({ items: members }))
}

function setup() {
  const onLoaded = vi.fn()
  const loader = useChapterLoader({ projectId: 'p1', chapterNo: '2.1', onLoaded })
  return { loader, onLoaded }
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUserId.value = ''
  mockApiOk()
})

describe('useChapterLoader · 身份就绪（直刷编辑器页面回归）', () => {
  it('currentUserId 为空（整页刷新）时，先补拉 /auth/me 再加载，成员判定按真实 ID', async () => {
    // 模拟 /auth/me 拉回当前用户为成员乙
    vi.mocked(fetchCurrentUserRole).mockImplementation(async () => {
      currentUserId.value = UID.member
    })
    const { loader, onLoaded } = setup()

    await loader.loadChapter()

    // 补拉发生且早于业务请求
    expect(fetchCurrentUserRole).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetchChapterContent).mock.invocationCallOrder[0]).toBeGreaterThan(
      vi.mocked(fetchCurrentUserRole).mock.invocationCallOrder[0],
    )
    // 真实成员 → 非误报
    expect(onLoaded).toHaveBeenCalledTimes(1)
    const data = onLoaded.mock.calls[0][0]
    expect(data.isProjectMember).toBe(true)
    // 分工任务装配正常（2.1 = submitted）
    expect(data.currentTask).toMatchObject({ chapter_no: '2.1', status: 'submitted' })
    expect(data.projectOwnerId).toBe(UID.owner)
  })

  it('currentUserId 已就绪（应用内导航）时不重复补拉', async () => {
    currentUserId.value = UID.member
    const { loader, onLoaded } = setup()

    await loader.loadChapter()

    expect(fetchCurrentUserRole).not.toHaveBeenCalled()
    expect(onLoaded).toHaveBeenCalledTimes(1)
    expect(onLoaded.mock.calls[0][0].isProjectMember).toBe(true)
  })

  it('补拉后仍不在成员列表 → isProjectMember=false（真实非成员，非误报）', async () => {
    // /auth/me 返回的账号不在该项目成员中
    vi.mocked(fetchCurrentUserRole).mockImplementation(async () => {
      currentUserId.value = '33333333-3333-4333-8333-333333333333'
    })
    const { loader, onLoaded } = setup()

    await loader.loadChapter()

    expect(fetchCurrentUserRole).toHaveBeenCalledTimes(1)
    expect(onLoaded).toHaveBeenCalledTimes(1)
    expect(onLoaded.mock.calls[0][0].isProjectMember).toBe(false)
  })

  it('owner 不在成员表（早期项目数据）时仍判定为项目内成员', async () => {
    // 模拟老项目：成员列表不含 owner，但 project.owner_id = 当前用户
    vi.mocked(fetchCurrentUserRole).mockImplementation(async () => {
      currentUserId.value = UID.owner
    })
    vi.mocked(fetchProjectMembers).mockResolvedValue(
      mkRes({ items: members.filter((m) => m.user_id !== UID.owner) }),
    )
    const { loader, onLoaded } = setup()

    await loader.loadChapter()

    expect(fetchCurrentUserRole).toHaveBeenCalledTimes(1)
    expect(onLoaded).toHaveBeenCalledTimes(1)
    expect(onLoaded.mock.calls[0][0].isProjectMember).toBe(true)
  })

  it('补拉异常（/auth/me 静默失败）不阻断加载流程', async () => {
    // fetchCurrentUserRole 内部 catch 后不抛错；当前用户仍未知
    vi.mocked(fetchCurrentUserRole).mockRejectedValue(new Error('boom'))
    const { loader, onLoaded } = setup()

    await loader.loadChapter()

    // 加载仍完成，成员判定按空 ID（不抛出未捕获异常）
    expect(onLoaded).toHaveBeenCalledTimes(1)
  })
})
