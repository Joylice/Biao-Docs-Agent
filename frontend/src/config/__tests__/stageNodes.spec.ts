/**
 * stageNodes 归并表测试：后端 8 个 stage_key → 前端 5 个投标编制节点.
 *
 * 口径真源 = 后端 migration 0029_unify_stages + runtime.STAGE_KEYS；
 * 本 spec 刻意用**硬编码期望值**（而非 import 常量自比）锁住口径 ——
 * 改归并表必须同步改测试，否则「测试通过」不再代表口径未漂移。
 */
import { describe, expect, it } from 'vitest'

import {
  BINDABLE_NODE_GROUPS,
  BINDABLE_STAGE_NODE_KEYS,
  findNodeOfStage,
  groupRoutesByNode,
  STAGE_KEY_ORDER,
  STAGE_NODE_GROUPS,
} from '@/config/stageNodes'

/** 后端 runtime.STAGE_KEYS 的 8 个 stage_key（勿随实现漂移） */
const BACKEND_STAGE_KEYS = [
  'parse',
  'score',
  'outline',
  'write',
  'validate',
  'consistency',
  'review',
  'export',
]

describe('STAGE_NODE_GROUPS', () => {
  it('恰好 5 个编制节点，序号 1..5 连续、key 唯一', () => {
    expect(STAGE_NODE_GROUPS).toHaveLength(5)
    expect(STAGE_NODE_GROUPS.map((g) => g.index)).toEqual([1, 2, 3, 4, 5])
    expect(new Set(STAGE_NODE_GROUPS.map((g) => g.key)).size).toBe(5)
  })

  it('节点名与归并口径逐条对齐 0029 迁移', () => {
    expect(STAGE_NODE_GROUPS.map((g) => [g.key, g.label, [...g.stageKeys]])).toEqual([
      ['parse', '招标解析', ['parse', 'score']],
      ['outline', '方案大纲生成', ['outline']],
      ['generate', '方案生成', ['write', 'validate', 'consistency']],
      ['review', '方案评审', ['review']],
      ['export', '方案导出', ['export']],
    ])
  })

  it('覆盖面成立：8 个后端 stage_key 全覆盖、不重复、无多余项', () => {
    expect([...STAGE_KEY_ORDER].sort()).toEqual([...BACKEND_STAGE_KEYS].sort())
    expect(STAGE_KEY_ORDER).toHaveLength(new Set(STAGE_KEY_ORDER).size)
  })
})

describe('findNodeOfStage', () => {
  it('按 stage_key 反查所属节点', () => {
    expect(findNodeOfStage('consistency')?.key).toBe('generate')
    expect(findNodeOfStage('score')?.index).toBe(1)
    expect(findNodeOfStage('export')?.label).toBe('方案导出')
  })

  it('未登记 / 已删阶段返回 undefined（negative control）', () => {
    expect(findNodeOfStage('rewrite')).toBeUndefined()
    expect(findNodeOfStage('')).toBeUndefined()
  })
})

describe('groupRoutesByNode', () => {
  it('组内顺序取归并表顺序（流水线顺序），不取入参顺序', () => {
    // 后端 GET /settings/routes 按 stage_key 字典序返回 → 故意乱序喂入
    const rows = [{ stageKey: 'write' }, { stageKey: 'consistency' }, { stageKey: 'validate' }]
    const groups = groupRoutesByNode(rows)

    expect(groups).toHaveLength(5)
    expect(groups.find((g) => g.key === 'generate')!.routes.map((r) => r.stageKey)).toEqual([
      'write',
      'validate',
      'consistency',
    ])
  })

  it('缺行不补空：未命中的 stage_key 从组内剔除', () => {
    const groups = groupRoutesByNode([{ stageKey: 'outline' }])

    expect(groups.find((g) => g.key === 'outline')!.routes).toHaveLength(1)
    expect(groups.find((g) => g.key === 'parse')!.routes).toEqual([])
    expect(groups.find((g) => g.key === 'generate')!.routes).toEqual([])
  })

  it('保留原始行对象引用（面板节点级编辑需就地写回）', () => {
    const row = { stageKey: 'review', model: 'a/b' }
    const hit = groupRoutesByNode([row]).find((g) => g.key === 'review')!.routes[0]

    expect(hit).toBe(row)
  })

  it('未登记 stage_key 不落入任何节点', () => {
    const groups = groupRoutesByNode([{ stageKey: 'rewrite' }, { stageKey: 'export' }])
    const total = groups.reduce((n, g) => n + g.routes.length, 0)

    expect(total).toBe(1)
    expect(groups.find((g) => g.key === 'export')!.routes).toHaveLength(1)
  })

  it('空入参返回 5 个空节点（不塌缩为 0 节点）', () => {
    const groups = groupRoutesByNode([])

    expect(groups).toHaveLength(5)
    expect(groups.every((g) => g.routes.length === 0)).toBe(true)
  })
})

describe('BINDABLE_NODE_GROUPS（外部工具绑定 UI 过滤集）', () => {
  it('恰好 4 个可绑定节点：排除「方案导出」（纯渲染阶段，无模型调用点）', () => {
    expect(BINDABLE_STAGE_NODE_KEYS).toEqual(['parse', 'outline', 'generate', 'review'])
    expect(BINDABLE_NODE_GROUPS.map((g) => g.key)).toEqual([
      'parse',
      'outline',
      'generate',
      'review',
    ])
    expect(BINDABLE_NODE_GROUPS.some((g) => g.key === 'export')).toBe(false)
  })

  it('是 STAGE_NODE_GROUPS 的真子集且保持流水线顺序（不新增/不改写节点）', () => {
    const fullOrder = STAGE_NODE_GROUPS.map((g) => g.key)
    expect(BINDABLE_NODE_GROUPS.map((g) => g.key)).toEqual(
      fullOrder.filter((k) => BINDABLE_STAGE_NODE_KEYS.includes(k)),
    )
    // 节点对象复用归并表实例，不是复制品（改归并表即同步生效）
    for (const g of BINDABLE_NODE_GROUPS) {
      expect(g).toBe(STAGE_NODE_GROUPS.find((n) => n.key === g.key))
    }
  })

  it('过滤集不影响 5 节点归并表本身（路由/概览/技能面板仍展示 5 行）', () => {
    expect(STAGE_NODE_GROUPS).toHaveLength(5)
    expect(STAGE_NODE_GROUPS.map((g) => g.label)).toContain('方案导出')
  })

  it('节点级绑定仍展开为组内全部 stage_key（方案生成 = 3 个）', () => {
    const generate = BINDABLE_NODE_GROUPS.find((g) => g.key === 'generate')!
    expect([...generate.stageKeys]).toEqual(['write', 'validate', 'consistency'])
  })
})
