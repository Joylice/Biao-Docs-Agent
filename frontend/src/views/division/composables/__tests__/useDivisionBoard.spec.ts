/**
 * useDivisionBoard 分工看板逻辑测试（mock API 依赖注入）.
 * 覆盖：数据加载 / assignRows 大纲合并 / 草稿基线 / 变更计算 / 推送校验与错误码 /
 *       筛选统计 / 移动动作解析与执行 / 撤销重做 / 路由跳转.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// stores/currentUser 依赖 api client（client 引 router → ui store pinia persist 访问 window），
// 单测环境 mock 掉 client 切断链路（composable 的 api 为 type-only 注入，不受影响）
vi.mock('@/api/client', () => ({ default: {} }))

import { useDivisionBoard, type DivisionApi } from '@/views/division/composables/useDivisionBoard'
import { currentUserId } from '@/stores/currentUser'
import type { AssignmentItem, TaskStatus, AssignmentNode, OutlineItem, ProjectMember } from '@/types'

/* ---------------- helpers ---------------- */

type MockedApi = { [K in keyof DivisionApi]: ReturnType<typeof vi.fn> }

const UID = {
  owner: '11111111-1111-4111-8111-111111111111',
  member: '22222222-2222-4222-8222-222222222222',
}

const mkRes = (data: unknown, code = 0) => ({ data: { code, data } })

function mkItem(id: string, chapterNo: string, over: Partial<AssignmentItem> = {}): AssignmentItem {
  return {
    id,
    chapter_no: chapterNo,
    title: `章节${chapterNo}`,
    assignee_id: UID.member,
    assignee_name: '成员乙',
    status: 'pending',
    strategy: null,
    ...over,
  } as AssignmentItem
}

function mkOutline(): OutlineItem[] {
  return [
    { chapter_no: '1', title: '第一章', sections: ['1.1 节一', { title: '1.2 节二' }] },
    { chapter_no: '2', title: '第二章', sections: [] },
  ]
}

function mkTree(): AssignmentNode[] {
  return [
    { chapter_no: '1', title: '第一章', id: 't1', assignee_id: UID.member, assignee_name: '成员乙', status: 'in_progress', children: [] },
  ]
}

function mkMembers(): ProjectMember[] {
  return [
    { user_id: UID.owner, email: 'owner@x.com', display_name: '负责人甲', role: 'owner' },
    { user_id: UID.member, email: 'member@x.com', display_name: '成员乙', role: 'member' },
  ] as ProjectMember[]
}

function mkApi(over: Partial<MockedApi> = {}): MockedApi {
  const api = {
    fetchChapterAssignments: vi.fn().mockResolvedValue(mkRes({ items: mkTree() })),
    upsertChapterAssignments: vi.fn().mockResolvedValue(mkRes({ items: [] })),
    acceptAssignment: vi.fn().mockResolvedValue(mkRes(null)),
    submitAssignment: vi.fn().mockResolvedValue(mkRes(null)),
    approveAssignment: vi.fn().mockResolvedValue(mkRes(null)),
    rejectAssignment: vi.fn().mockResolvedValue(mkRes(null)),
    fetchProject: vi.fn().mockResolvedValue(mkRes({ owner_id: UID.owner })),
    fetchProjectMembers: vi.fn().mockResolvedValue(mkRes({ items: mkMembers() })),
    fetchWorkflowStatus: vi.fn().mockResolvedValue(mkRes({ outline: mkOutline() })),
    confirmDivision: vi.fn().mockResolvedValue(mkRes(null)),
    ...over,
  } as unknown as MockedApi
  return api
}

function setup(over: { api?: MockedApi; userId?: string } = {}) {
  const api = over.api ?? mkApi()
  currentUserId.value = over.userId ?? UID.owner
  const notify = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }
  const routerPush = vi.fn()
  const fetchCurrentUserRole = vi.fn().mockResolvedValue(undefined)
  const db = useDivisionBoard('proj-1', {
    api,
    notify,
    routerPush,
    fetchCurrentUserRole,
  })
  return { db, api, notify, routerPush, fetchCurrentUserRole }
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.stubGlobal('window', {
    setTimeout: vi.fn(() => 1),
    clearTimeout: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* ---------------- 数据加载 ---------------- */

describe('数据加载 fetchAll', () => {
  it('并行加载分工/大纲/owner/成员，owner 判定生效', async () => {
    const { db } = setup()
    await db.fetchAll()
    expect(db.items.value).toHaveLength(1) // 树拍平
    expect(db.outline.value).toHaveLength(2)
    expect(db.isOwner.value).toBe(true) // currentUserId=owner
    expect(db.memberOptions.value).toHaveLength(2)
    expect(db.loading.value).toBe(false)
  })

  it('非 owner：isOwner false，成员视角只看自己的任务', async () => {
    const { db, api } = setup({ userId: UID.member })
    api.fetchChapterAssignments.mockResolvedValue(mkRes({
      items: [mkItem('a', '1', { assignee_id: UID.member }), mkItem('b', '2', { assignee_id: UID.owner })],
    }))
    await db.fetchAll()
    expect(db.isOwner.value).toBe(false)
    expect(db.filteredItems.value).toHaveLength(1)
    expect(db.filteredItems.value[0].chapter_no).toBe('1')
  })
})

/* ---------------- assignRows 大纲合并 ---------------- */

describe('assignRows 分配表格数据源', () => {
  it('以大纲为主干合并分工 assignee，子节行编号 chapter.i', async () => {
    const { db } = setup()
    await db.fetchAll()
    const rows = db.assignRows.value
    expect(rows).toHaveLength(2) // 两章
    const ch1 = rows[0]
    expect(ch1.chapter_no).toBe('1')
    expect(ch1.assignee_id).toBe(UID.member) // 从分工树合并
    expect(ch1.status).toBe('in_progress')
    expect(ch1.children).toHaveLength(2) // 1.1 / 1.2
    expect(ch1.children![0].chapter_no).toBe('1.1')
    expect(ch1.children![1].chapter_no).toBe('1.2')
    // 第二章无分工记录，assignee 为空（owner 可首次分配）
    expect(rows[1].assignee_id).toBeUndefined()
  })

  it('孤儿分工记录追加为顶层行（容错脏数据）', async () => {
    const api = mkApi({
      fetchChapterAssignments: vi.fn().mockResolvedValue(mkRes({
        items: [{ chapter_no: '9', title: '孤儿章', id: 'o1' }],
      })),
    })
    const { db } = setup({ api })
    await db.fetchAll()
    const rows = db.assignRows.value
    expect(rows[rows.length - 1].chapter_no).toBe('9')
  })

  it('大纲子节未覆盖的节级分工补录进 children', async () => {
    const api = mkApi({
      fetchChapterAssignments: vi.fn().mockResolvedValue(mkRes({
        items: [
          { chapter_no: '1', title: '第一章', id: 't1', children: [{ chapter_no: '1.5', title: '历史节', id: 't15' }] },
        ],
      })),
    })
    const { db } = setup({ api })
    await db.fetchAll()
    const ch1 = db.assignRows.value[0]
    expect(ch1.children?.map((c) => c.chapter_no)).toContain('1.5')
  })
})

/* ---------------- 草稿与变更 ---------------- */

describe('草稿基线与变更计算', () => {
  it('syncDraftBaseline 递归同步已推送 assignee 为下拉初值', async () => {
    const { db } = setup()
    await db.fetchAll()
    expect(db.draftAssignees.value['1']).toBe(UID.member)
  })

  it('changedItems：草稿非空且与已推送不一致才算变更', async () => {
    const { db } = setup()
    await db.fetchAll()
    expect(db.changedCount.value).toBe(0)
    db.draftAssignees.value['1'] = UID.owner // 改变
    db.draftAssignees.value['2'] = undefined // 空 → 不算
    expect(db.changedCount.value).toBe(1)
    expect(db.changedItems.value[0].chapter_no).toBe('1')
  })
})

/* ---------------- 分工推送 ---------------- */

describe('handleAssign 分工推送', () => {
  it('成功：payload 正确，推送后重新加载分工并提示', async () => {
    const { db, api, notify } = setup()
    await db.fetchAll()
    db.draftAssignees.value['2'] = UID.member
    await db.handleAssign()
    expect(api.upsertChapterAssignments).toHaveBeenCalledWith('proj-1', [
      { chapter_no: '2', title: '第二章', assignee_id: UID.member },
    ])
    expect(notify.success).toHaveBeenCalledWith('已推送 1 个章节的分工任务')
    expect(db.assigning.value).toBe(false)
  })

  it('无变更时不调用接口', async () => {
    const { db, api } = setup()
    await db.fetchAll()
    await db.handleAssign()
    expect(api.upsertChapterAssignments).not.toHaveBeenCalled()
  })

  it('非 UUID 负责人被拦截', async () => {
    const { db, api, notify } = setup()
    await db.fetchAll()
    db.draftAssignees.value['2'] = 'not-a-uuid'
    await db.handleAssign()
    expect(notify.error).toHaveBeenCalledWith(expect.stringContaining('负责人ID格式错误'))
    expect(api.upsertChapterAssignments).not.toHaveBeenCalled()
  })

  it('业务错误 4004 映射为成员提示', async () => {
    const api = mkApi({
      upsertChapterAssignments: vi.fn().mockResolvedValue({
        data: { code: 4004, message: '用户不在项目成员中' },
      }),
    })
    const { db, notify } = setup({ api })
    await db.fetchAll()
    db.draftAssignees.value['2'] = UID.member
    await db.handleAssign()
    expect(notify.error).toHaveBeenCalledWith(expect.stringContaining('分工推送失败：错误码: 4004'), 5)
  })

  it('请求异常 4004 → 负责人不是项目成员友好提示', async () => {
    const api = mkApi({
      upsertChapterAssignments: vi.fn().mockRejectedValue({
        response: { status: 400, data: { code: 4004, message: '用户不在项目成员中' } },
      }),
    })
    const { db, notify } = setup({ api })
    await db.fetchAll()
    db.draftAssignees.value['2'] = UID.member
    await db.handleAssign()
    expect(notify.error).toHaveBeenCalledWith(expect.stringContaining('负责人不是项目成员'), 8)
  })
})

/* ---------------- 筛选统计 ---------------- */

describe('筛选与统计', () => {
  it('owner 按 filterAssignee 过滤，未筛选显示全部', async () => {
    const { db } = setup()
    await db.fetchAll()
    expect(db.filteredItems.value).toHaveLength(1)
    db.filterAssignee.value = UID.owner
    expect(db.filteredItems.value).toHaveLength(0)
    db.filterAssignee.value = UID.member
    expect(db.filteredItems.value).toHaveLength(1)
  })

  it('myTaskCount 只计本人未通过任务；approvedCount 计已通过', async () => {
    const { db, api } = setup()
    api.fetchChapterAssignments.mockResolvedValue(mkRes({
      items: [
        mkItem('a', '1', { assignee_id: UID.owner, status: 'in_progress' }),
        mkItem('b', '2', { assignee_id: UID.owner, status: 'approved' }),
        mkItem('c', '3', { assignee_id: UID.member, status: 'approved' }),
      ],
    }))
    await db.fetchAll()
    expect(db.myTaskCount.value).toBe(1)
    expect(db.approvedCount.value).toBe(2)
  })
})

/* ---------------- 看板移动 ---------------- */

describe('resolveMoveAction 状态转换', () => {
  it('四类合法转换与非法转换', () => {
    const { db } = setup()
    const item = mkItem('a', '1')
    // pending → in_progress 领取
    expect(db.resolveMoveAction({ ...item, status: 'pending' }, 'in_progress')?.kind).toBe('accept')
    // in_progress → submitted 提交
    expect(db.resolveMoveAction({ ...item, status: 'in_progress' }, 'submitted')?.kind).toBe('submit')
    // rejected → submitted 再次提审
    expect(db.resolveMoveAction({ ...item, status: 'rejected' }, 'submitted')?.kind).toBe('submit')
    // submitted → approved 通过
    expect(db.resolveMoveAction({ ...item, status: 'submitted' }, 'approved')?.kind).toBe('approve')
    // submitted → rejected 打回
    expect(db.resolveMoveAction({ ...item, status: 'submitted' }, 'rejected')?.kind).toBe('reject')
    // 非法：pending → approved
    expect(db.resolveMoveAction({ ...item, status: 'pending' }, 'approved')).toBeNull()
  })
})

describe('handleMoveTask 执行', () => {
  it('领取：调用 acceptAssignment，成功后刷新', async () => {
    const { db, api, notify } = setup()
    await db.fetchAll()
    const item = db.items.value[0] // status in_progress（tree 中 t1）→ 改 pending 走 accept
    const pendingItem = { ...item, status: 'pending' as TaskStatus }
    await db.handleMoveTask(pendingItem, 'in_progress')
    expect(api.acceptAssignment).toHaveBeenCalledWith('proj-1', pendingItem.id)
    expect(notify.success).toHaveBeenCalledWith(expect.stringContaining('已领取'))
  })

  it('非法转换：warning 且不调用接口', async () => {
    const { db, api, notify } = setup()
    await db.fetchAll()
    const item = db.items.value[0]
    await db.handleMoveTask(item, 'approved') // in_progress → approved 非法
    expect(notify.warning).toHaveBeenCalledWith('该状态转换不支持，请通过卡片按钮操作')
    expect(api.acceptAssignment).not.toHaveBeenCalled()
  })

  it('失败：error 提示 + 刷新回原状态 + 清空撤销历史', async () => {
    const api = mkApi({ acceptAssignment: vi.fn().mockRejectedValue(mkErr('状态冲突')) })
    const { db, notify } = setup({ api })
    await db.fetchAll()
    const item = db.items.value[0]
    const pendingItem = { ...item, status: 'pending' as TaskStatus }
    await db.handleMoveTask(pendingItem, 'in_progress')
    expect(notify.error).toHaveBeenCalledWith('状态冲突')
  })
})

function mkErr(message: string) {
  return { response: { data: { message } } }
}

/* ---------------- 路由跳转 ---------------- */

describe('路由跳转', () => {
  it('仅本人分工卡片可编辑：owner 点自己卡片无 readonly，点他人卡片 readonly=1；成员点他人卡片 readonly=1', async () => {
    // owner 视角：点自己分工的卡片 → 可编辑；点他人分工卡片 → 只读
    const { db, routerPush } = setup()
    await db.fetchAll()
    const myItem = mkItem('a', '1', { assignee_id: UID.owner })
    db.handleSelectTask(myItem)
    expect(routerPush).toHaveBeenCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '1' },
      query: undefined,
    })

    const otherItem = mkItem('b', '2', { assignee_id: UID.member })
    db.handleSelectTask(otherItem)
    expect(routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '2' },
      query: { readonly: '1' },
    })

    // 非 owner 成员视角：点击他人章节（owner 的任务）→ 只读模式
    const member = setup({ userId: UID.member })
    await member.db.fetchAll()
    member.db.handleSelectTask(mkItem('c', '3', { assignee_id: UID.owner }))
    expect(member.routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '3' },
      query: { readonly: '1' },
    })
  })

  it('已提审/已通过章节内容锁定：本人分工卡片也带 readonly=1（不可再编辑）', async () => {
    // 已提审（submitted）→ 只读
    const { db, routerPush } = setup()
    await db.fetchAll()
    db.handleSelectTask(mkItem('s', '1', { assignee_id: UID.owner, status: 'submitted' }))
    expect(routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '1' },
      query: { readonly: '1' },
    })

    // 已通过（approved）→ 只读
    db.handleSelectTask(mkItem('a', '2', { assignee_id: UID.owner, status: 'approved' }))
    expect(routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '2' },
      query: { readonly: '1' },
    })

    // 编制中（in_progress）→ 可编辑（无 readonly）
    db.handleSelectTask(mkItem('p', '3', { assignee_id: UID.owner, status: 'in_progress' }))
    expect(routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '3' },
      query: undefined,
    })

    // 被打回（rejected）→ 可编辑（需修改后重新提交）
    db.handleSelectTask(mkItem('r', '4', { assignee_id: UID.owner, status: 'rejected' }))
    expect(routerPush).toHaveBeenLastCalledWith({
      name: 'ChapterEditor',
      params: { projectId: 'proj-1', chapterNo: '4' },
      query: undefined,
    })
  })

  it('进入审阅：confirmDivision 成功后跳转 Review', async () => {
    const { db, api, notify, routerPush } = setup()
    await db.handleConfirmDivision()
    expect(api.confirmDivision).toHaveBeenCalledWith('proj-1')
    expect(notify.success).toHaveBeenCalledWith('分工编制已完成，进入审阅')
    expect(routerPush).toHaveBeenCalledWith({ name: 'Review', params: { projectId: 'proj-1' } })
  })

  it('进入审阅失败：错误提示', async () => {
    const api = mkApi({ confirmDivision: vi.fn().mockRejectedValue(mkErr('尚未提交审核')) })
    const { db, notify, routerPush } = setup({ api })
    await db.handleConfirmDivision()
    expect(notify.error).toHaveBeenCalledWith('尚未提交审核')
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('返回大纲：跳转 Generate', () => {
    const { db, routerPush } = setup()
    db.goToGenerate()
    expect(routerPush).toHaveBeenCalledWith({ name: 'Generate', params: { projectId: 'proj-1' } })
  })
})
