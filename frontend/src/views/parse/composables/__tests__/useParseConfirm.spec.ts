/**
 * useParseConfirm 招标解析确认页逻辑测试（mock API 依赖注入）.
 * 覆盖：数据加载 / 派生统计 / 防抖自动保存与 flush /
 *       保存确认三闸门 / 工作流推进（interrupt/轮询）/ 批量确认与策略 / 格式与废标.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useParseConfirm, type ScorePoint, type ParseConfirmApi, type ParseConfirmNotify } from '@/views/parse/composables/useParseConfirm'

/* ---------------- helpers ---------------- */

const mkRes = (data: unknown, code = 0) => ({ data: { code, data } })
const mkErr = (message: string) => ({ response: { data: { message } } })

function mkScorePoint(id: string, over: Partial<ScorePoint> = {}): ScorePoint {
  return {
    id,
    clause_no: '4.1',
    item: `评分点${id}`,
    score: 10,
    criteria: null,
    is_star: false,
    risk_level: null,
    strategy: null,
    confirmed: false,
    ...over,
  }
}

function mkApi(over: Partial<Record<keyof ParseConfirmApi, ReturnType<typeof vi.fn>>> = {}) {
  const api = {
    fetchScorePoints: vi.fn().mockResolvedValue(mkRes([mkScorePoint('a'), mkScorePoint('b', { score: 25, confirmed: true }), mkScorePoint('c', { score: 20 }), mkScorePoint('d', { score: 5, confirmed: true })])),
    updateScorePoint: vi.fn().mockResolvedValue(mkRes(null)),
    downloadProjectDocument: vi.fn().mockResolvedValue({ data: new Blob(['x']) }),
    reparseDocument: vi.fn().mockResolvedValue(mkRes(null)),
    fetchDocFormatRequirements: vi.fn().mockResolvedValue(mkRes({ items: [{ category: 'other', requirement: '格式1' }] })),
    saveDocFormatRequirements: vi.fn().mockResolvedValue(mkRes({ items: [{ category: 'other', requirement: '格式1' }, { category: 'other', requirement: '格式2' }] })),
    fetchDocDisqualificationClauses: vi.fn().mockResolvedValue(mkRes({ items: [{ id: 'd1', clause_no: '8.1', title: '废标条款', risk_category: '高', severity: '严重', recommendation: '注意', confirmed: false }] })),
    saveDocDisqualificationClauses: vi.fn().mockResolvedValue(mkRes(null)),
    fetchProjectDocuments: vi.fn().mockResolvedValue(mkRes({ items: [{ id: 'doc1', title: '招标文件.pdf', status: 'parsed' }] })),
    fetchWorkflowStatus: vi.fn().mockResolvedValue(mkRes({ interrupt: { type: 'confirm_score_points' }, phase: 'confirm' })),
    startWorkflow: vi.fn().mockResolvedValue(mkRes(null)),
    confirmScorePoints: vi.fn().mockResolvedValue(mkRes(null)),
    ...over,
  } as unknown as ParseConfirmApi
  return api
}

function setup(over: { api?: ParseConfirmApi; notify?: Partial<ParseConfirmNotify> } = {}) {
  const api = over.api ?? mkApi()
  const notify: ParseConfirmNotify = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(() => vi.fn()),
    ...over.notify,
  }
  const routerPush = vi.fn()
  const pc = useParseConfirm('proj-1', { api, notify, routerPush })
  return { pc, api, notify, routerPush }
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.stubGlobal('window', {
    setTimeout: vi.fn(() => 1),
    clearTimeout: vi.fn(),
    location: { reload: vi.fn() },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

/* ---------------- 数据加载 ---------------- */

describe('fetchData 数据加载', () => {
  it('加载评分点与招标文档，并加载格式/废标/术语表', async () => {
    const { pc, api } = setup()
    await pc.fetchData()
    expect(api.fetchScorePoints).toHaveBeenCalledWith('proj-1')
    // 4 条评分点
    expect(pc.scorePoints.value).toHaveLength(4)
    // 文档 + 格式 + 废标
    expect(pc.tenderDoc.value?.id).toBe('doc1')
    expect(pc.formatRequirements.value).toHaveLength(1)
    expect(pc.disqualificationClauses.value).toHaveLength(1)
    expect(pc.loading.value).toBe(false)
    expect(pc.loadError.value).toBe('')
  })

  it('加载失败设置 loadError', async () => {
    const api = mkApi({ fetchScorePoints: vi.fn().mockRejectedValue(new Error('boom')) })
    const { pc } = setup({ api })
    await pc.fetchData()
    expect(pc.loadError.value).toBe('解析数据加载失败')
    expect(pc.loading.value).toBe(false)
  })

  it('无招标文档时跳过格式/废标加载', async () => {
    const api = mkApi({ fetchProjectDocuments: vi.fn().mockResolvedValue(mkRes({ items: [] })) })
    const { pc, api: a } = setup({ api })
    await pc.fetchData()
    expect(pc.tenderDoc.value).toBeNull()
    expect(a.fetchDocFormatRequirements).not.toHaveBeenCalled()
  })
})

/* ---------------- 派生统计 ---------------- */

describe('派生统计', () => {
  it('确认计数/百分比/总分/高风险/未确认高风险', async () => {
    const { pc } = setup()
    await pc.fetchData()
    expect(pc.confirmedCount.value).toBe(2)
    expect(pc.confirmedPercent.value).toBe(50)
    expect(pc.totalScore.value).toBe(60)
    expect(pc.highRiskCount.value).toBe(2) // 25 和 20
    expect(pc.unconfirmedHighRiskCount.value).toBe(1) // 20 分未确认
    expect(pc.canGenerate.value).toBe(true)
    expect(pc.canSaveConfirm.value).toBe(true)
    expect(pc.canReparse.value).toBe(true)
  })

  it('空列表：百分比 0、canGenerate false', async () => {
    const api = mkApi({ fetchScorePoints: vi.fn().mockResolvedValue(mkRes([])) })
    const { pc } = setup({ api })
    await pc.fetchData()
    expect(pc.confirmedPercent.value).toBe(0)
    expect(pc.canGenerate.value).toBe(false)
    expect(pc.highRiskCount.value).toBe(0)
  })
})

/* ---------------- 防抖自动保存 ---------------- */

describe('handleAutoSave / flushPendingSaves', () => {
  it('行内修改防抖 1s 后落库', async () => {
    vi.useFakeTimers()
    const { pc, api } = setup()
    const row = mkScorePoint('a', { strategy: '策略A', confirmed: true })
    pc.handleAutoSave(row)
    expect(api.updateScorePoint).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(api.updateScorePoint).toHaveBeenCalledWith('proj-1', 'a', { strategy: '策略A', confirmed: true })
    vi.useRealTimers()
  })

  it('flush 强制落库防抖队列中的行', async () => {
    vi.useFakeTimers()
    const { pc, api } = setup()
    await pc.fetchData()
    const row = pc.scorePoints.value[0]
    row.strategy = '待落库'
    pc.handleAutoSave(row)
    await pc.flushPendingSaves()
    expect(api.updateScorePoint).toHaveBeenCalledWith('proj-1', row.id, { strategy: '待落库', confirmed: false })
    vi.useRealTimers()
  })

  it('flush 无待保存行时直接返回', async () => {
    const { pc, api } = setup()
    await pc.flushPendingSaves()
    expect(api.updateScorePoint).not.toHaveBeenCalled()
  })
})

/* ---------------- 保存确认三闸门 ---------------- */

describe('handleSaveAll 三闸门', () => {
  it('无评分点 → info 提示', async () => {
    const api = mkApi({ fetchScorePoints: vi.fn().mockResolvedValue(mkRes([])) })
    const { pc, notify } = setup({ api })
    await pc.fetchData()
    await pc.handleSaveAll()
    expect(notify.info).toHaveBeenCalledWith('暂无评分点需要保存')
  })

  it('未全部确认 → warning', async () => {
    const { pc, notify } = setup()
    await pc.fetchData()
    await pc.handleSaveAll()
    expect(notify.warning).toHaveBeenCalledWith('还有 2 条评分点未确认')
  })

  it('已全部确认 → success', async () => {
    const { pc, notify } = setup()
    await pc.fetchData()
    // 全部置为 confirmed
    for (const p of pc.scorePoints.value) p.confirmed = true
    await pc.handleSaveAll()
    expect(notify.success).toHaveBeenCalledWith('评分点已全部确认，可以生成大纲')
  })
})

/* ---------------- 工作流推进 ---------------- */

describe('handleConfirm 工作流推进', () => {
  it('interrupt 已就绪：确认 → 跳转 Generate', async () => {
    const { pc, api, notify, routerPush } = setup()
    await pc.fetchData()
    await pc.handleConfirm()
    expect(api.confirmScorePoints).toHaveBeenCalledWith('proj-1')
    expect(notify.success).toHaveBeenCalledWith('已确认，开始生成大纲...')
    expect(routerPush).toHaveBeenCalledWith('Generate', { projectId: 'proj-1' })
    expect(pc.confirming.value).toBe(false)
  })

  it('phase=init 时启动工作流并轮询至 interrupt', async () => {
    vi.useFakeTimers()
    const fetchWorkflowStatus = vi
      .fn()
      .mockResolvedValueOnce(mkRes({ phase: 'init' })) // 首次：无 interrupt
      .mockResolvedValue(mkRes({ interrupt: { type: 'confirm_score_points' }, phase: 'confirm' }))
    const api = mkApi({ fetchWorkflowStatus })
    const { pc, api: a } = setup({ api })
    await pc.fetchData()
    const p = pc.handleConfirm()
    await vi.advanceTimersByTimeAsync(1000)
    await p
    expect(a.startWorkflow).toHaveBeenCalledWith('proj-1')
    expect(a.confirmScorePoints).toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('工作流已进入后续阶段 → warning 并中止', async () => {
    const api = mkApi({ fetchWorkflowStatus: vi.fn().mockResolvedValue(mkRes({ interrupt: { type: 'other' }, phase: 'generate' })) })
    const { pc, notify, api: a } = setup({ api })
    await pc.fetchData()
    await pc.handleConfirm()
    expect(notify.warning).toHaveBeenCalledWith('工作流已进入后续阶段，请前往「方案大纲生成」页继续操作')
    expect(a.confirmScorePoints).not.toHaveBeenCalled()
  })
})

/* ---------------- 批量操作 ---------------- */

describe('批量操作', () => {
  it('批量确认：仅处理勾选且未确认项，成功提示', async () => {
    const { pc, api, notify } = setup()
    await pc.fetchData()
    // 勾选 a（未确认）与 b（已确认）
    pc.selectedRowKeys.value = ['a', 'b']
    await pc.handleConfirmAll()
    expect(api.updateScorePoint).toHaveBeenCalledWith('proj-1', 'a', { confirmed: true })
    expect(pc.scorePoints.value.find((p) => p.id === 'a')?.confirmed).toBe(true)
    expect(notify.success).toHaveBeenCalledWith('已确认 1 条评分点')
  })

  it('批量确认：无待确认项 → info 并清空勾选', async () => {
    const { pc, api, notify } = setup()
    await pc.fetchData()
    pc.selectedRowKeys.value = ['b', 'd'] // 均已确认
    await pc.handleConfirmAll()
    expect(notify.info).toHaveBeenCalledWith('所选评分点已全部确认')
    expect(pc.selectedRowKeys.value).toEqual([])
    expect(api.updateScorePoint).not.toHaveBeenCalled()
  })

  it('批量策略：空内容警告；有效内容应用到全部', async () => {
    const { pc, api, notify } = setup()
    await pc.fetchData()
    await pc.handleApplyBatchStrategy()
    expect(notify.warning).toHaveBeenCalledWith('请输入策略内容')

    pc.batchStrategy.value = ' 统一策略 '
    await pc.handleApplyBatchStrategy()
    expect(api.updateScorePoint).toHaveBeenCalledTimes(4)
    expect(pc.scorePoints.value.every((p) => p.strategy === '统一策略')).toBe(true)
    expect(notify.success).toHaveBeenCalledWith('已应用到全部 4 条评分点')
    expect(pc.batchStrategyOpen.value).toBe(false)
  })
})

/* ---------------- 格式与废标 ---------------- */

describe('格式要求与废标条款', () => {
  it('新增/删除格式项', async () => {
    const { pc } = setup()
    pc.handleAddFormatItem()
    pc.handleAddFormatItem()
    expect(pc.formatRequirements.value).toHaveLength(2)
    const item = pc.formatRequirements.value[0]
    pc.handleRemoveFormatItem(item)
    expect(pc.formatRequirements.value).toHaveLength(1)
  })

  it('保存格式：过滤空内容，保存后回填 id 键', async () => {
    const { pc, api, notify } = setup()
    await pc.fetchData()
    pc.formatRequirements.value = [
      { key: 'k1', category: 'other', requirement: '格式A' },
      { key: 'k2', category: 'other', requirement: '   ' },
    ]
    await pc.handleSaveFormat()
    expect(api.saveDocFormatRequirements).toHaveBeenCalledWith(
      'proj-1',
      'doc1',
      [{ category: 'other', requirement: '格式A' }],
    )
    expect(pc.formatRequirements.value).toHaveLength(2)
    expect(notify.success).toHaveBeenCalledWith('格式要求已保存（2 条）')
    expect(pc.formatSaving.value).toBe(false)
  })

  it('废标确认失败时回滚 confirmed', async () => {
    const api = mkApi({ saveDocDisqualificationClauses: vi.fn().mockRejectedValue(mkErr('网络错误')) })
    const { pc, notify } = setup({ api })
    await pc.fetchData()
    const clause = pc.disqualificationClauses.value[0]
    await pc.handleDisqualificationConfirm(clause, true)
    expect(clause.confirmed).toBe(false) // 回滚
    expect(notify.error).toHaveBeenCalledWith('网络错误')
    expect(pc.disqualificationSaving.value).toBe(false)
  })
})
