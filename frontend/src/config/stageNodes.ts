/**
 * stageNodes：投标编制节点（5 个）与流水线阶段（8 个 stage_key）的归并映射 —— 展示层单一真源.
 *
 * 口径来源（勿凭记忆改写，两处必须同时满足）：
 *   1. 后端 `app/services/infra/settings/runtime.py` 的 `STAGE_KEYS`：8 个 stage_key
 *      （parse / score / outline / write / validate / consistency / review / export）；
 *   2. 后端 migration `0029_unify_stages`：「service 层 stage_key 参数不变，
 *      前端展示层做归并映射」。
 *
 * ⇒ 展示层（阶段路由面板 / 配置概览）一律经本模块归并为 5 个投标编制节点；
 *    禁止在组件内重复定义归并表（曾因 OverviewPanel 自行平铺 8 行而与导航
 *    文案「5 个编制节点的模型分配」不一致）。
 *
 * 归并口径（逐条对齐 0029 迁移）：
 *   ① 招标解析     = parse + score
 *   ② 方案大纲生成 = outline
 *   ③ 方案生成     = write + validate + consistency
 *   ④ 方案评审     = review
 *   ⑤ 方案导出     = export
 *
 * 注意：本模块只做**展示归并**，不下发后端。保存仍按 stage_key 逐条提交
 * （见 useRoutesConfig.save），节点级编辑由调用方负责同步写入组内全部 stage_key。
 */

/** 单个投标编制节点定义（stage_key 归并映射） */
export interface StageNodeGroup {
  /** 节点 id：前端展示层分组键，非后端字段（勿用于任何 API 入参） */
  key: string
  /** 节点序号 1..5（展示顺序） */
  index: number
  /** 节点中文名（5 个投标编制节点口径） */
  label: string
  /** 归并到本节点的 stage_key，顺序 = 节点内展示顺序（也是流水线先后） */
  stageKeys: readonly string[]
}

/** 5 个投标编制节点（数组顺序 = 展示顺序 = 流水线顺序） */
export const STAGE_NODE_GROUPS: readonly StageNodeGroup[] = [
  { key: 'parse', index: 1, label: '招标解析', stageKeys: ['parse', 'score'] },
  { key: 'outline', index: 2, label: '方案大纲生成', stageKeys: ['outline'] },
  {
    key: 'generate',
    index: 3,
    label: '方案生成',
    stageKeys: ['write', 'validate', 'consistency'],
  },
  { key: 'review', index: 4, label: '方案评审', stageKeys: ['review'] },
  { key: 'export', index: 5, label: '方案导出', stageKeys: ['export'] },
]

/**
 * 全部受管 stage_key（8 个）的展示顺序 = 节点顺序 × 节点内顺序.
 * 与后端 STAGE_KEYS 为同一集合，顺序按业务流水线而非字典序。
 */
export const STAGE_KEY_ORDER: readonly string[] = STAGE_NODE_GROUPS.flatMap((g) => g.stageKeys)

/**
 * 可绑定外部工具（网络搜索）的编制节点 key —— **仅供外部工具绑定 UI 过滤**.
 *
 * 为什么不直接删「方案导出」组：本表的 5 节点口径同时服务阶段路由面板 / 配置概览 /
 * 技能关联，删行会让这些面板少一个节点；而「绑定不生效」只取决于该节点下 stage
 * 是否有 LLM 调用点，属绑定 UI 的关注点 ⇒ 用过滤集表达，不动归并表本身。
 *
 * 判定依据 = 节点内是否存在已接线外部工具取证的 stage
 * （`app/services/infra/tools/prefetch.py` 的 prefetch_external_evidence）：
 *   招标解析（parse 已接线；score 无独立调用，随节点一并绑定无害）
 *   / 方案大纲生成（outline）/ 方案生成（write + validate + consistency）
 *   / 方案评审（review）；「方案导出」（export）为纯渲染阶段，无模型调用点。
 */
export const BINDABLE_STAGE_NODE_KEYS: readonly string[] = [
  'parse',
  'outline',
  'generate',
  'review',
]

/** 可绑定节点列表（顺序同 STAGE_NODE_GROUPS = 流水线顺序） */
export const BINDABLE_NODE_GROUPS: readonly StageNodeGroup[] = STAGE_NODE_GROUPS.filter((g) =>
  BINDABLE_STAGE_NODE_KEYS.includes(g.key),
)

/** 按 stage_key 反查所属编制节点；未登记返回 undefined */
export function findNodeOfStage(stageKey: string): StageNodeGroup | undefined {
  return STAGE_NODE_GROUPS.find((g) => g.stageKeys.includes(stageKey))
}

/**
 * 泛型归并：把任意「带 stageKey 的路由行」按 5 个编制节点分组.
 *
 * 组内顺序取 `STAGE_NODE_GROUPS` 的 stageKeys 顺序（流水线顺序），
 * 不取入参数组顺序 —— 后端 GET /settings/routes 按 stage_key 字典序返回，
 * 直接沿用会把「方案生成」组显示成 consistency/validate/write，与流水线相反。
 * 入参缺失某个 stage_key 行时该子阶段从组内静默剔除（不补空行）。
 */
export function groupRoutesByNode<T extends { stageKey: string }>(
  routes: readonly T[],
): Array<StageNodeGroup & { routes: T[] }> {
  return STAGE_NODE_GROUPS.map((group) => ({
    ...group,
    routes: group.stageKeys
      .map((stageKey) => routes.find((r) => r.stageKey === stageKey))
      .filter((r): r is T => r !== undefined),
  }))
}
