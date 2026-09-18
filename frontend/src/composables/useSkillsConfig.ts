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

/** 技能（阶段）视图行：OverviewPanel/SkillsPanel 渲染与快照共用 */
export interface SkillRow {
  stageKey: string
  stageName: string
  enabled: boolean
  /** 绑定到该阶段的外部工具名列表（会话内推断口径） */
  boundToolNames: string[]
}

/**
 * 纯函数：routes + tools + bindings → 技能视图行（供面板渲染与单测直接覆盖）。
 */
export function buildSkillRows(
  routes: ModelRoute[],
  tools: ExternalTool[],
  bindings: Record<string, string[]>,
): SkillRow[] {
  return routes.map((route) => ({
    stageKey: route.stageKey,
    stageName: route.stageName,
    enabled: route.enabled,
    boundToolNames: tools
      .filter((t) => (bindings[t.id] ?? []).includes(route.stageKey))
      .map((t) => t.name),
  }))
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
  /** 技能视图行（computed，面板直接渲染） */
  skillRows: ComputedRef<SkillRow[]>
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

  const skillRows = computed(() => buildSkillRows(routes.value, tools.value, bindings.value))

  async function load(): Promise<void> {
    loading.value = true
    try {
      const [routeRows, toolRows] = await Promise.all([getRoutes(), getTools()])
      routes.value = routeRows
      tools.value = toolRows
      bindings.value = {}
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

  return { loading, routes, tools, bindings, skillRows, load, toggleEnabled, bindStage, unbindStage }
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
