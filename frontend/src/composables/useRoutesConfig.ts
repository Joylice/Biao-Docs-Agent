/**
 * useRoutesConfig：阶段路由条目（P1-5）逻辑模型.
 *
 * 数据：GET /settings/routes（8 个流水线阶段）；编辑字段为
 * model / temperature / max_tokens / timeout（fallback/thinking/enabled
 * 本条目不开放编辑，保存 payload 不携带）。
 * 保存：仅对用户触碰过的阶段逐个 PUT /settings/routes/{stageKey}（批量并发），
 * 未触碰阶段不打扰后端。实现为「依赖注入工厂 + 模块级单例」（同
 * useProvidersConfig，面板切换不丢编辑态；单测注入 mock API）。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  getRoutes,
  updateRoute,
  type ModelRoute,
  type RouteUpdatePayload,
} from '@/api/providers'
import { getApiErrorMessage } from './apiErrorMessage'

export interface RoutesConfigDeps {
  getRoutes: () => Promise<ModelRoute[]>
  updateRoute: (stageKey: string, payload: RouteUpdatePayload) => Promise<unknown>
  notifyError: (msg: string) => void
}

export interface RoutesConfigApi {
  loading: Ref<boolean>
  routes: Ref<ModelRoute[]>
  /** 用户触碰过（需要保存）的 stage_key 集合 */
  changedStages: Ref<Set<string>>
  isDirty: ComputedRef<boolean>
  load: () => Promise<void>
  touch: (stageKey: string) => void
  save: () => Promise<void>
}

export function createRoutesConfig(deps: RoutesConfigDeps): RoutesConfigApi {
  const { getRoutes, updateRoute, notifyError } = deps

  const loading = ref(false)
  const routes = ref<ModelRoute[]>([])
  const changedStages = ref<Set<string>>(new Set())

  const isDirty = computed(() => changedStages.value.size > 0)

  async function load(): Promise<void> {
    loading.value = true
    try {
      routes.value = await getRoutes()
      changedStages.value.clear()
    } catch (error) {
      notifyError(getApiErrorMessage(error, '加载阶段路由失败'))
    } finally {
      loading.value = false
    }
  }

  /** 面板编辑回调：标记该阶段需要保存 */
  function touch(stageKey: string): void {
    changedStages.value.add(stageKey)
  }

  /**
   * 批量保存：仅保存触碰过的阶段（Promise.all 并发）；失败抛 Error
   * （store 保留脏状态、changedStages 不清空），成功后 reload 并清空脏集合。
   * 无改动直接返回（视为保存成功）。
   */
  async function save(): Promise<void> {
    if (changedStages.value.size === 0) return
    const targets = routes.value.filter((r) => changedStages.value.has(r.stageKey))
    try {
      await Promise.all(
        targets.map((route) =>
          updateRoute(route.stageKey, {
            model: route.model,
            temperature: route.temperature ?? undefined,
            max_tokens: route.maxTokens ?? undefined,
            timeout: route.timeout ?? undefined,
          }),
        ),
      )
    } catch (error) {
      throw new Error(getApiErrorMessage(error, '保存阶段路由失败'))
    }
    await load()
  }

  return { loading, routes, changedStages, isDirty, load, touch, save }
}

/* ---------------- 模块级单例 ---------------- */

let singleton: RoutesConfigApi | null = null

export function useRoutesConfig(): RoutesConfigApi {
  if (!singleton) {
    singleton = createRoutesConfig({
      getRoutes,
      updateRoute,
      notifyError: (msg) => message.error(msg),
    })
  }
  return singleton
}
