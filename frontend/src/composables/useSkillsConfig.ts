/**
 * useSkillsConfig：技能分类（P1-3）逻辑模型.
 *
 * 「技能」= 流水线阶段的业务视图（旧 SkillsView 的阶段绑定管理部分迁移，
 * 该文件 T05 下线不修改）：列表来自 GET /settings/routes（8 阶段的名称/
 * 启用态），启停 = PUT /settings/routes/{stage_key} { enabled }（后端无
 * 路由乐观锁，即时保存）；阶段绑定 = 该阶段绑定的外部工具（数据源为
 * useExternalToolsConfig 的 tools + 会话内 bindings，bind/unbind 走
 * /settings/external-tools/{id}/bind 端点）。
 *
 * 实现为「依赖注入工厂 + 模块级单例」（单测经 createSkillsConfig 注入）。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  getRoutes,
  updateRoute,
  type ModelRoute,
  type RouteUpdatePayload,
} from '@/api/providers'
import {
  bindExternalTool,
  getExternalTools,
  unbindExternalTool,
  type ExternalTool,
} from '@/api/externalTools'
import { getApiErrorMessage } from './apiErrorMessage'
import { STAGE_NODE_GROUPS } from '@/config/stageNodes'

/** 工具绑定的单个阶段（用于工具卡内逐阶段展示 / 启停 / 解绑） */
export interface ToolBoundStage {
  stageKey: string
  stageName: string
  /** 该阶段是否启用（阶段级，与工具自身启用态相互独立） */
  stageEnabled: boolean
}

/**
 * 工具（外部工具）视图行：SkillsPanel 渲染与单测共用.
 *
 * 口径：本面板以「外部工具」为主实体，每个工具关联其绑定的投标编制节点
 * （经 @/config/stageNodes 的 STAGE_NODE_GROUPS 归并，对齐 5 节点口径）。
 * 绑定关系本质仍是「阶段 ↔ 工具」（后端 bind/unbind 以 stage_key 为键），
 * 此处仅做**展示层反转**：工具 → 其所属编制节点 + 已绑定阶段。
 */
export interface ToolRow {
  toolId: string
  toolName: string
  /** 工具自身启用态（ExternalTool.enabled，仅展示，本面板不就地切换） */
  toolEnabled: boolean
  /** 关联编制节点 key（去重，顺序同 STAGE_NODE_GROUPS） */
  nodeKeys: string[]
  /** 关联编制节点中文名 */
  nodeLabels: string[]
  /** 该工具已绑定的阶段 */
  boundStages: ToolBoundStage[]
}

/**
 * 纯函数：routes + tools + bindings → 工具视图行（供面板渲染与单测直接覆盖）。
 *
 * nodeKeys/nodeLabels 取 STAGE_NODE_GROUPS 顺序归并，不依赖入参顺序；
 * 绑定中引用了 routes 不存在的 stage_key 时静默剔除（与 groupRoutesByNode 一致）。
 */
export function buildToolRows(
  routes: ModelRoute[],
  tools: ExternalTool[],
  bindings: Record<string, string[]>,
): ToolRow[] {
  const routeByKey = new Map(routes.map((r) => [r.stageKey, r]))
  return tools.map((tool) => {
    const boundKeys = bindings[tool.id] ?? []
    const boundStages: ToolBoundStage[] = boundKeys
      .map((stageKey) => routeByKey.get(stageKey))
      .filter((r): r is ModelRoute => r !== undefined)
      .map((r) => ({ stageKey: r.stageKey, stageName: r.stageName, stageEnabled: r.enabled }))
    const nodeKeys = STAGE_NODE_GROUPS.filter((g) =>
      g.stageKeys.some((sk) => boundKeys.includes(sk)),
    ).map((g) => g.key)
    return {
      toolId: tool.id,
      toolName: tool.name,
      toolEnabled: tool.enabled,
      nodeKeys,
      nodeLabels: STAGE_NODE_GROUPS.filter((g) => nodeKeys.includes(g.key)).map((g) => g.label),
      boundStages,
    }
  })
}

export interface SkillsConfigDeps {
  getRoutes: () => Promise<ModelRoute[]>
  updateRoute: (stageKey: string, payload: RouteUpdatePayload) => Promise<unknown>
  getTools: () => Promise<ExternalTool[]>
  bindTool: (id: string, payload: { stage_key: string }) => Promise<unknown>
  unbindTool: (id: string, stageKey: string) => Promise<void>
  notifyError: (msg: string) => void
  notifySuccess: (msg: string) => void
}

export interface SkillsConfigApi {
  loading: Ref<boolean>
  routes: Ref<ModelRoute[]>
  tools: Ref<ExternalTool[]>
  /** toolId → 绑定的 stage_key[]（会话内推断，load 后为空） */
  bindings: Ref<Record<string, string[]>>
  /** 工具视图行（computed，面板直接渲染，工具为主、关联编制节点） */
  toolRows: ComputedRef<ToolRow[]>
  load: () => Promise<void>
  /** 启停（即时保存）；失败返回 false（开关 UI 由调用方回滚） */
  toggleEnabled: (stageKey: string, enabled: boolean) => Promise<boolean>
  bindStage: (tool: ExternalTool, stageKey: string) => Promise<boolean>
  unbindStage: (tool: ExternalTool, stageKey: string) => Promise<boolean>
}

export function createSkillsConfig(deps: SkillsConfigDeps): SkillsConfigApi {
  const { getRoutes, updateRoute, getTools, bindTool, unbindTool, notifyError, notifySuccess } = deps

  const loading = ref(false)
  const routes = ref<ModelRoute[]>([])
  const tools = ref<ExternalTool[]>([])
  const bindings = ref<Record<string, string[]>>({})

  const toolRows = computed(() => buildToolRows(routes.value, tools.value, bindings.value))

  async function load(): Promise<void> {
    loading.value = true
    try {
      const [routeRows, toolRows] = await Promise.all([getRoutes(), getTools()])
      routes.value = routeRows
      tools.value = toolRows
      // 用后端回填的 boundStages 初始化绑定映射，使首屏即展示工具↔编制节点关联
      // （而非会话内乐观更新后才出现）。绑定/解绑操作仍经下方 bind/unbind 更新此映射。
      bindings.value = Object.fromEntries(
        toolRows.map((t) => [t.id, [...(t.boundStages ?? [])]]),
      )
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载技能配置失败'))
    } finally {
      loading.value = false
    }
  }

  async function toggleEnabled(stageKey: string, enabled: boolean): Promise<boolean> {
    try {
      await updateRoute(stageKey, { enabled })
      const row = routes.value.find((r) => r.stageKey === stageKey)
      if (row) row.enabled = enabled
      notifySuccess(enabled ? `阶段「${row?.stageName ?? stageKey}」已启用` : '阶段已停用')
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '更新失败，请刷新后重试'))
      return false
    }
  }

  async function bindStage(tool: ExternalTool, stageKey: string): Promise<boolean> {
    try {
      await bindTool(tool.id, { stage_key: stageKey })
      const list = bindings.value[tool.id] ?? []
      if (!list.includes(stageKey)) {
        bindings.value = { ...bindings.value, [tool.id]: [...list, stageKey] }
      }
      notifySuccess('已绑定')
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '绑定失败'))
      return false
    }
  }

  async function unbindStage(tool: ExternalTool, stageKey: string): Promise<boolean> {
    try {
      await unbindTool(tool.id, stageKey)
      bindings.value = {
        ...bindings.value,
        [tool.id]: (bindings.value[tool.id] ?? []).filter((s) => s !== stageKey),
      }
      notifySuccess('已解绑')
      return true
    } catch (error) {
      notifyError(getApiErrorMessage(error, '解绑失败'))
      return false
    }
  }

  return { loading, routes, tools, bindings, toolRows, load, toggleEnabled, bindStage, unbindStage }
}

/* ---------------- 模块级单例 ---------------- */

let singleton: SkillsConfigApi | null = null

export function useSkillsConfig(): SkillsConfigApi {
  if (!singleton) {
    singleton = createSkillsConfig({
      getRoutes,
      updateRoute,
      getTools: getExternalTools,
      bindTool: bindExternalTool,
      unbindTool: unbindExternalTool,
      notifySuccess: (msg) => message.success(msg),
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
